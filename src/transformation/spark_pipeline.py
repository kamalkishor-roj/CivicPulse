"""
PySpark Medallion Transformation Pipeline for CivicPulse
Distributed batch transformation with schema validation, window-based deduplication,
SCD Type 2 status history generation, and BigQuery loading.
"""

import os
from typing import Optional, Dict, Any, List
from config.settings import settings
from config.logging_config import logger


class PySparkPipeline:
    """
    Distributed PySpark pipeline for Medallion Architecture (Bronze -> Silver -> Gold).
    """

    def __init__(self, app_name: str = "CivicPulse-PySpark-Pipeline"):
        self.app_name = app_name
        self._spark = None

    @property
    def spark(self):
        """Lazy initialization of SparkSession."""
        if self._spark is None:
            from pyspark.sql import SparkSession
            builder = (
                SparkSession.builder.appName(self.app_name)
                .master("local[*]")
                .config("spark.sql.adaptive.enabled", "true")
                .config("spark.sql.shuffle.partitions", "4")
                .config("spark.driver.memory", "2g")
                .config("spark.sql.legacy.timeParserPolicy", "CORRECTED")
            )
            # Add BigQuery connector jar if running in cloud
            if settings.storage_backend == "gcs":
                builder = builder.config(
                    "spark.jars.packages",
                    "com.google.cloud.spark:spark-bigquery-with-dependencies_2.12:0.36.0"
                )
            self._spark = builder.getOrCreate()
            logger.info(f"Initialized SparkSession: version={self._spark.version}")
        return self._spark

    def run_pipeline(self, raw_json_paths: List[str]) -> Dict[str, Any]:
        """
        Executes distributed transformations on raw partitioned JSON snapshots.
        """
        from pyspark.sql import functions as F
        from pyspark.sql.window import Window

        logger.info(f"Starting PySpark pipeline on {len(raw_json_paths)} raw files...")
        spark = self.spark

        # Read JSON snapshots
        raw_df = spark.read.json(raw_json_paths)

        # Flatten records array if stored in batch envelopes
        if "records" in raw_df.columns:
            exploded_df = raw_df.select(
                F.col("batch_id").alias("source_batch_id"),
                F.col("ingested_at").alias("source_ingested_at"),
                F.explode("records").alias("rec")
            ).select("source_batch_id", "source_ingested_at", "rec.*")
        else:
            exploded_df = raw_df

        # Standardize core identifiers across SODA / Open311 variations
        standardized_df = exploded_df.withColumn(
            "service_request_id",
            F.coalesce(F.col("sr_number"), F.col("service_request_id"))
        ).withColumn(
            "sr_type",
            F.coalesce(F.col("sr_type"), F.col("type_of_service_request"))
        ).withColumn(
            "agency",
            F.coalesce(F.col("owner_department"), F.col("agency_responsible"), F.lit("Unknown Agency"))
        ).withColumn(
            "created_dt",
            F.to_timestamp(F.col("created_date"))
        ).withColumn(
            "modified_dt",
            F.coalesce(F.to_timestamp(F.col("last_modified_date")), F.to_timestamp(F.col("created_date")))
        ).withColumn(
            "closed_dt",
            F.to_timestamp(F.col("closed_date"))
        ).withColumn(
            "lat_val",
            F.col("latitude").cast("double")
        ).withColumn(
            "lon_val",
            F.col("longitude").cast("double")
        )

        # -------------------------------------------------------------
        # 1. Data Quality Checks & Quarantine Routing
        # -------------------------------------------------------------
        quality_cond = (
            F.col("service_request_id").isNotNull() &
            (F.col("service_request_id") != "") &
            F.col("sr_type").isNotNull() &
            F.col("status").isNotNull() &
            F.col("created_dt").isNotNull() &
            (
                F.col("closed_dt").isNull() |
                (F.col("closed_dt") >= F.col("created_dt"))
            ) &
            (
                F.col("lat_val").isNull() |
                (
                    (F.col("lat_val") >= settings.chicago_min_lat) &
                    (F.col("lat_val") <= settings.chicago_max_lat) &
                    (F.col("lon_val") >= settings.chicago_min_lon) &
                    (F.col("lon_val") <= settings.chicago_max_lon)
                )
            )
        )

        valid_df = standardized_df.filter(quality_cond)
        quarantine_df = standardized_df.filter(~quality_cond)

        quarantined_count = quarantine_df.count()
        valid_count = valid_df.count()
        logger.info(f"PySpark DQ Split: {valid_count} valid records, {quarantined_count} quarantined records.")

        # -------------------------------------------------------------
        # 2. SCD Type 2 Status History Engine (Window Functions)
        # -------------------------------------------------------------
        # Order distinct status updates chronologically for each service request
        scd_window = Window.partitionBy("service_request_id").orderBy("modified_dt")

        scd2_base = valid_df.select(
            "service_request_id",
            F.initcap("status").alias("status"),
            F.col("modified_dt").alias("effective_start_date")
        ).dropDuplicates(["service_request_id", "status", "effective_start_date"])

        # Compute next status start date as current status end date using LEAD()
        scd2_with_lead = scd2_base.withColumn(
            "effective_end_date",
            F.lead("effective_start_date").over(scd_window)
        ).withColumn(
            "is_current",
            F.when(F.col("effective_end_date").isNull(), True).otherwise(False)
        ).withColumn(
            "version",
            F.row_number().over(scd_window)
        ).withColumn(
            "duration_in_status_hours",
            F.when(
                F.col("effective_end_date").isNotNull(),
                F.round((F.col("effective_end_date").cast("long") - F.col("effective_start_date").cast("long")) / 3600.0, 2)
            ).otherwise(F.lit(None).cast("double"))
        ).withColumn(
            "status_history_sk",
            F.md5(F.concat_ws("_", F.col("service_request_id"), F.col("status"), F.col("effective_start_date")))
        )

        # -------------------------------------------------------------
        # 3. Silver Service Requests (Deduplicated Current State)
        # -------------------------------------------------------------
        dedup_window = Window.partitionBy("service_request_id").orderBy(F.col("modified_dt").desc())

        silver_current = valid_df.withColumn(
            "row_num",
            F.row_number().over(dedup_window)
        ).filter(F.col("row_num") == 1).drop("row_num").withColumn(
            "resolution_time_hours",
            F.when(
                F.col("closed_dt").isNotNull(),
                F.round((F.col("closed_dt").cast("long") - F.col("created_dt").cast("long")) / 3600.0, 2)
            ).otherwise(F.lit(None).cast("double"))
        ).withColumn(
            "record_hash",
            F.sha2(F.concat_ws("|", F.col("status"), F.col("agency"), F.col("street_address")), 256)
        )

        # -------------------------------------------------------------
        # 4. Gold Aggregations
        # -------------------------------------------------------------
        gold_resolution = silver_current.filter(F.col("closed_dt").isNotNull()).groupBy("sr_type").agg(
            F.count("*").alias("total_resolved"),
            F.round(F.avg("resolution_time_hours"), 2).alias("avg_resolution_hours"),
            F.expr("percentile_approx(resolution_time_hours, 0.50)").alias("median_resolution_hours"),
            F.expr("percentile_approx(resolution_time_hours, 0.90)").alias("p90_resolution_hours")
        )

        gold_backlog = silver_current.filter(~F.col("status").isin(["Completed", "Closed", "Cancelled"])).groupBy("agency").agg(
            F.count("*").alias("total_backlog")
        )

        return {
            "status": "SUCCESS",
            "valid_records": valid_count,
            "quarantined_records": quarantined_count,
            "silver_count": silver_current.count(),
            "scd2_count": scd2_with_lead.count()
        }

    def stop(self) -> None:
        """Stops the SparkSession."""
        if self._spark:
            self._spark.stop()
            self._spark = None
