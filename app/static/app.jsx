const { useState, useEffect, useRef } = React;

function App() {
  const [activeTab, setActiveTab] = useState('map'); // Default to Map as requested
  const [agencyFilter, setAgencyFilter] = useState('ALL');
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');
  
  const [kpis, setKpis] = useState({
    total_complaints: 0,
    total_resolved: 0,
    total_backlog: 0,
    resolution_rate_pct: 0,
    avg_resolution_hours: 0,
    reopen_rate_pct: 0,
    critical_backlog_30d: 0
  });

  const [watermark, setWatermark] = useState({
    last_extracted_watermark: 'Loading...',
    total_records_extracted: 0,
    status: 'ACTIVE'
  });

  const [mapPoints, setMapPoints] = useState([]);
  const [scdCandidates, setScdCandidates] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState('');
  const [scdHistory, setScdHistory] = useState([]);
  const [velocityData, setVelocityData] = useState([]);
  const [backlogData, setBacklogData] = useState([]);
  const [quarantineData, setQuarantineData] = useState({ total_quarantined: 0, reasons_breakdown: {}, sample_records: [] });
  const [isIngesting, setIsIngesting] = useState(false);

  const mapInstanceRef = useRef(null);
  const markersLayerRef = useRef(null);

  // Initial Data Fetch
  useEffect(() => {
    fetchWatermark();
    fetchScdCandidates();
    fetchQuarantine();
    fetchBacklogs();
    fetchVelocity();
  }, []);

  // Filter-dependent data fetch
  useEffect(() => {
    fetchKpis();
    fetchMapPoints();
  }, [agencyFilter, categoryFilter, statusFilter]);

  // Fetch single incident history when selection changes
  useEffect(() => {
    if (selectedIncident) {
      fetchScdHistory(selectedIncident);
    }
  }, [selectedIncident]);

  const fetchWatermark = async () => {
    try {
      const res = await fetch('/api/state');
      if (res.ok) setWatermark(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchKpis = async () => {
    try {
      const url = `/api/kpis?agency=${agencyFilter}&category=${categoryFilter}&status=${statusFilter}`;
      const res = await fetch(url);
      if (res.ok) setKpis(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchMapPoints = async () => {
    try {
      const url = `/api/map-points?agency=${agencyFilter}&category=${categoryFilter}&limit=400`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setMapPoints(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchScdCandidates = async () => {
    try {
      const res = await fetch('/api/scd2/candidates');
      if (res.ok) {
        const data = await res.json();
        setScdCandidates(data);
        if (data.length > 0 && !selectedIncident) {
          setSelectedIncident(data[0].service_request_id);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchScdHistory = async (id) => {
    try {
      const res = await fetch(`/api/scd2/history/${id}`);
      if (res.ok) setScdHistory(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchVelocity = async () => {
    try {
      const res = await fetch('/api/resolution-velocity');
      if (res.ok) setVelocityData(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchBacklogs = async () => {
    try {
      const res = await fetch('/api/agency-backlogs');
      if (res.ok) setBacklogData(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchQuarantine = async () => {
    try {
      const res = await fetch('/api/quarantine');
      if (res.ok) setQuarantineData(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const handleTriggerIngestion = async () => {
    setIsIngesting(true);
    try {
      const res = await fetch('/api/ingest', { method: 'POST' });
      if (res.ok) {
        await fetchWatermark();
        await fetchKpis();
        await fetchMapPoints();
        await fetchScdCandidates();
        await fetchBacklogs();
        await fetchVelocity();
        await fetchQuarantine();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsIngesting(false);
    }
  };

  // -------------------------------------------------------------
  // Leaflet Map Initialization & Rendering (ZERO API KEY REQUIRED)
  // -------------------------------------------------------------
  useEffect(() => {
    if (activeTab === 'map') {
      setTimeout(() => {
        const mapContainer = document.getElementById('chicago-map');
        if (!mapContainer) return;

        if (!mapInstanceRef.current) {
          // Initialize Leaflet Map centered on Chicago
          const map = L.map('chicago-map', {
            center: [41.8781, -87.6298],
            zoom: 11,
            zoomControl: true
          });

          // OpenStreetMap Tile Layer - 100% FREE & ZERO API KEY NEEDED
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          }).addTo(map);

          mapInstanceRef.current = map;
          markersLayerRef.current = L.layerGroup().addTo(map);
        }

        // Invalidate map size so it renders fully without grey tiles
        mapInstanceRef.current.invalidateSize();

        // Update Map Markers
        if (markersLayerRef.current) {
          markersLayerRef.current.clearLayers();

          mapPoints.forEach((pt) => {
            const lat = parseFloat(pt.latitude);
            const lon = parseFloat(pt.longitude);
            if (isNaN(lat) || isNaN(lon)) return;

            // Color-code based on responsible agency
            let color = '#2563eb'; // CDOT Blue
            if (pt.agency.includes('Streets')) color = '#d97706'; // Streets & San Amber
            if (pt.agency.includes('Water')) color = '#059669'; // DWM Emerald

            const marker = L.circleMarker([lat, lon], {
              radius: 6,
              fillColor: color,
              color: '#ffffff',
              weight: 1.5,
              opacity: 0.9,
              fillOpacity: 0.8
            });

            const popupContent = `
              <div style="font-family: inherit; font-size: 12px; line-height: 1.5;">
                <div style="font-weight: 800; color: #38bdf8; font-size: 13px; margin-bottom: 4px;">${pt.sr_type}</div>
                <div><strong>ID:</strong> <code style="color: #94a3b8;">${pt.service_request_id}</code></div>
                <div><strong>Agency:</strong> ${pt.agency}</div>
                <div><strong>Status:</strong> <span style="font-weight: bold; color: ${pt.status === 'Completed' ? '#34d399' : '#fbbf24'}">${pt.status}</span></div>
                <div><strong>Address:</strong> ${pt.street_address || 'Chicago, IL'}</div>
                <div><strong>Ward:</strong> ${pt.ward || 'N/A'}</div>
                <div style="margin-top: 4px; font-size: 11px; color: #94a3b8;">Created: ${pt.created_date ? pt.created_date.substring(0, 16) : 'N/A'}</div>
              </div>
            `;
            marker.bindPopup(popupContent);
            markersLayerRef.current.addLayer(marker);
          });
        }
      }, 100);
    }
  }, [activeTab, mapPoints]);

  return (
    <div className="max-w-[1600px] mx-auto p-4 md:p-6 space-y-6">
      
      {/* Executive Command Header */}
      <header className="bg-gradient-to-r from-slate-900 via-slate-800 to-indigo-950 border border-slate-700/60 rounded-2xl p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-3xl">🏙️</span>
            <div>
              <h1 className="text-2xl font-black tracking-tight text-white flex items-center gap-2">
                CivicPulse <span className="text-sm font-semibold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">React Edition</span>
              </h1>
              <p className="text-xs text-slate-400 mt-1">Chicago 311 Public Infrastructure Lakehouse &bull; Medallion Architecture (Bronze &bull; Silver &bull; Gold)</p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <div className="inline-flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
            Lakehouse Active
          </div>

          <div className="text-right text-xs text-slate-400 hidden sm:block">
            <div>Watermark: <strong className="font-mono text-slate-200">{watermark.last_extracted_watermark ? watermark.last_extracted_watermark.substring(0, 19) : ''}</strong></div>
            <div>Total Ingested: <strong className="text-slate-200">{watermark.total_records_extracted ? watermark.total_records_extracted.toLocaleString() : 0}</strong> records</div>
          </div>

          <button 
            onClick={handleTriggerIngestion}
            disabled={isIngesting}
            className={`px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all shadow-lg ${
              isIngesting 
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed' 
                : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-600/30 active:scale-95'
            }`}
          >
            {isIngesting ? (
              <>
                <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>
                Ingesting...
              </>
            ) : (
              <>
                <span>⚡</span> Ingest Next Batch
              </>
            )}
          </button>
        </div>
      </header>

      {/* Global Interactive Filter Bar */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="font-bold text-slate-400 uppercase tracking-wider">Filters:</span>

          {/* Agency Filter */}
          <select 
            value={agencyFilter}
            onChange={(e) => setAgencyFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="ALL">All Municipal Agencies</option>
            <option value="CDOT - Department of Transportation">CDOT - Transportation</option>
            <option value="Streets and Sanitation">Streets and Sanitation</option>
            <option value="DWM - Department of Water Management">DWM - Water Management</option>
          </select>

          {/* Category Filter */}
          <select 
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="ALL">All Complaint Categories</option>
            <option value="Pothole in Street Complaint">Pothole in Street</option>
            <option value="Garbage Cart Maintenance">Garbage Cart Maintenance</option>
            <option value="Water in Basement">Water in Basement / Flood</option>
            <option value="Street Light 1 Out">Street Light 1 Out</option>
            <option value="Street Lights - All Out">Street Lights - All Out</option>
            <option value="Fly Dumping / Illegal Dumping">Illegal Fly Dumping</option>
            <option value="Graffiti Removal">Graffiti Removal</option>
          </select>

          {/* Status Filter */}
          <select 
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="ALL">All Statuses</option>
            <option value="BACKLOG">Active Backlog Only</option>
            <option value="RESOLVED">Resolved / Completed</option>
            <option value="REOPENED">Reopened Complaints</option>
          </select>
        </div>

        <div className="text-xs text-slate-400">
          Showing: <strong className="text-indigo-400">{mapPoints.length}</strong> geocoded incidents on map
        </div>
      </div>

      {/* KPI Hero Scorecards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-blue-500"></div>
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Total Complaints</div>
          <div className="text-3xl font-black text-white mt-2">{kpis.total_complaints.toLocaleString()}</div>
          <div className="text-xs text-slate-400 mt-2 flex items-center gap-1">
            <span className="text-blue-400 font-semibold">100%</span> Lakehouse integrity
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-emerald-500"></div>
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Resolved Complaints</div>
          <div className="text-3xl font-black text-white mt-2">{kpis.total_resolved.toLocaleString()}</div>
          <div className="text-xs text-emerald-400 font-semibold mt-2">
            {kpis.resolution_rate_pct}% resolution rate
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-amber-500"></div>
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Active Backlog</div>
          <div className="text-3xl font-black text-white mt-2">{kpis.total_backlog.toLocaleString()}</div>
          <div className="text-xs text-amber-400 font-semibold mt-2">
            {kpis.critical_backlog_30d} tickets &gt; 30 days
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-cyan-500"></div>
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Avg Resolution Velocity</div>
          <div className="text-3xl font-black text-white mt-2">{kpis.avg_resolution_hours}<span className="text-base font-semibold text-slate-400">h</span></div>
          <div className="text-xs text-slate-400 mt-2">
            City Target: &le; 72.0h
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm relative overflow-hidden col-span-2 md:col-span-1">
          <div className="absolute top-0 left-0 right-0 h-1 bg-rose-500"></div>
          <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Reopened Rate</div>
          <div className="text-3xl font-black text-white mt-2">{kpis.reopen_rate_pct}%</div>
          <div className="text-xs text-rose-400 font-semibold mt-2">
            Recidivism indicator
          </div>
        </div>

      </div>

      {/* Navigation Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-slate-800 text-sm font-semibold pb-1">
        <button 
          onClick={() => setActiveTab('map')}
          className={`px-4 py-2.5 rounded-lg transition-all flex items-center gap-2 ${
            activeTab === 'map' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <span>🗺️</span> Interactive Chicago Map <span className="bg-emerald-500/20 text-emerald-300 text-[10px] px-1.5 py-0.5 rounded uppercase font-bold border border-emerald-500/30">Zero API Key</span>
        </button>

        <button 
          onClick={() => setActiveTab('scd2')}
          className={`px-4 py-2.5 rounded-lg transition-all flex items-center gap-2 ${
            activeTab === 'scd2' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <span>🔄</span> SCD Type 2 Incident Journey
        </button>

        <button 
          onClick={() => setActiveTab('velocity')}
          className={`px-4 py-2.5 rounded-lg transition-all flex items-center gap-2 ${
            activeTab === 'velocity' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <span>⏱️</span> Resolution Velocity
        </button>

        <button 
          onClick={() => setActiveTab('backlog')}
          className={`px-4 py-2.5 rounded-lg transition-all flex items-center gap-2 ${
            activeTab === 'backlog' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <span>🏢</span> Agency Backlog
        </button>

        <button 
          onClick={() => setActiveTab('quarantine')}
          className={`px-4 py-2.5 rounded-lg transition-all flex items-center gap-2 ${
            activeTab === 'quarantine' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <span>🛡️</span> Data Quality Quarantine
        </button>
      </div>

      {/* ========================================================= */}
      {/* TAB 1: INTERACTIVE CHICAGO MAP (ZERO API KEY REQUIRED)     */}
      {/* ========================================================= */}
      {activeTab === 'map' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                Geospatial Infrastructure Breakdown Map
              </h2>
              <p className="text-xs text-slate-400">
                Powered by <strong>Leaflet.js &amp; OpenStreetMap</strong>. Requires <strong>NO API keys</strong>, tokens, or signups. 100% visible and interactive.
              </p>
            </div>

            {/* Map Legend */}
            <div className="flex flex-wrap items-center gap-4 text-xs font-semibold bg-slate-800/80 px-3 py-2 rounded-xl border border-slate-700">
              <span className="text-slate-400">Legend:</span>
              <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-blue-500 inline-block border border-white/50"></span> CDOT (Transportation)</div>
              <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-amber-500 inline-block border border-white/50"></span> Streets &amp; Sanitation</div>
              <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-emerald-500 inline-block border border-white/50"></span> Water Management</div>
            </div>
          </div>

          {/* Leaflet DOM Node */}
          <div id="chicago-map" className="border border-slate-700/60 shadow-inner"></div>

          <div className="text-xs text-slate-400 flex justify-between items-center pt-1">
            <span>💡 Click on any circle marker to view incident details, category, and street address.</span>
            <span>Total geocoded coordinates: <strong>{mapPoints.length}</strong></span>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 2: SCD TYPE 2 INCIDENT JOURNEY VISUALIZER              */}
      {/* ========================================================= */}
      {activeTab === 'scd2' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                Slowly Changing Dimension (Type 2) Status History Explorer
              </h2>
              <p className="text-xs text-slate-400">
                Maintains full historical intervals (<code>effective_start_date</code>, <code>effective_end_date</code>, <code>version</code>, <code>duration_in_status_hours</code>).
              </p>
            </div>

            <div className="flex items-center gap-3">
              <label className="text-xs font-bold text-slate-400 uppercase">Select Incident:</label>
              <select 
                value={selectedIncident} 
                onChange={(e) => setSelectedIncident(e.target.value)}
                className="bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none"
              >
                {scdCandidates.map(c => (
                  <option key={c.service_request_id} value={c.service_request_id}>
                    Incident {c.service_request_id} ({c.sr_type} - {c.transition_count} transitions)
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Horizontal Stepper Timeline */}
          <div className="flex flex-wrap md:flex-nowrap items-center gap-4 py-4 overflow-x-auto">
            {scdHistory.map((step, idx) => {
              const isCurrent = step.is_current;
              const borderClass = isCurrent ? 'border-emerald-500 bg-emerald-500/10' : 'border-blue-500 bg-blue-500/10';
              const textClass = isCurrent ? 'text-emerald-400' : 'text-blue-400';

              return (
                <div key={idx} className={`flex-1 min-w-[220px] border-2 ${borderClass} rounded-2xl p-5 text-center relative shadow-sm`}>
                  <div className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest">Version {step.version}</div>
                  <div className={`text-lg font-black ${textClass} my-1.5`}>{step.status}</div>
                  <div className="text-[11px] font-mono text-slate-300 leading-tight">
                    <div>{step.effective_start_date ? step.effective_start_date.substring(0, 16) : ''}</div>
                    <div className="text-slate-500">&darr;</div>
                    <div>{step.effective_end_date}</div>
                  </div>
                  <div className="mt-3 inline-block bg-slate-800 border border-slate-700 text-[11px] font-bold px-3 py-1 rounded-full text-slate-200">
                    {step.duration_in_status_hours ? `${step.duration_in_status_hours} hrs` : 'Current Active State'}
                  </div>
                </div>
              );
            })}
          </div>

          {/* SCD2 Ledger Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border border-slate-800 rounded-xl overflow-hidden">
              <thead className="bg-slate-800/80 text-slate-400 uppercase font-bold text-[11px]">
                <tr>
                  <th className="p-3">Version</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Effective Start Date</th>
                  <th className="p-3">Effective End Date</th>
                  <th className="p-3">Active Flag</th>
                  <th className="p-3">Duration (Hours)</th>
                  <th className="p-3">Surrogate Key (SK)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-slate-300">
                {scdHistory.map((row, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/50">
                    <td className="p-3 font-mono font-bold">v{row.version}</td>
                    <td className="p-3 font-bold text-white">{row.status}</td>
                    <td className="p-3 font-mono">{row.effective_start_date}</td>
                    <td className="p-3 font-mono">{row.effective_end_date}</td>
                    <td className="p-3">
                      {row.is_current ? (
                        <span className="text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">TRUE</span>
                      ) : (
                        <span className="text-slate-500">FALSE</span>
                      )}
                    </td>
                    <td className="p-3 font-mono">{row.duration_in_status_hours ? `${row.duration_in_status_hours}h` : '—'}</td>
                    <td className="p-3 font-mono text-slate-500">{row.status_history_sk}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 3: RESOLUTION VELOCITY & SLA                          */}
      {/* ========================================================= */}
      {activeTab === 'velocity' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div>
            <h2 className="text-lg font-bold text-white">Resolution Time Velocity by Complaint Category</h2>
            <p className="text-xs text-slate-400">Comparing mean, median, and 90th percentile resolution hours against the 72-hour city SLA.</p>
          </div>

          <div className="space-y-4">
            {velocityData.map((item, idx) => {
              const hours = item.avg_hours;
              const isOverSLA = hours > 72.0;
              const widthPct = Math.min(Math.round((hours / 200) * 100), 100);

              return (
                <div key={idx} className="bg-slate-800/50 border border-slate-800 rounded-xl p-4 space-y-2">
                  <div className="flex flex-wrap justify-between items-center text-xs">
                    <span className="font-bold text-white text-sm">{item.sr_type}</span>
                    <div className="flex items-center gap-4">
                      <span className="text-slate-400">Resolved: <strong className="text-slate-200">{item.resolved_count}</strong></span>
                      <span className="text-slate-400">Median: <strong className="text-slate-200">{item.median_hours}h</strong></span>
                      <span className="text-slate-400">P90: <strong className="text-slate-200">{item.p90_hours}h</strong></span>
                      <span className={`font-black px-2 py-0.5 rounded ${isOverSLA ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'}`}>
                        Avg: {hours}h {isOverSLA ? '(SLA Breach)' : '(SLA OK)'}
                      </span>
                    </div>
                  </div>

                  {/* Progress Bar */}
                  <div className="w-full bg-slate-800 h-2.5 rounded-full overflow-hidden border border-slate-700/60 relative">
                    <div 
                      className={`h-full rounded-full ${isOverSLA ? 'bg-rose-500' : 'bg-emerald-500'}`}
                      style={{ width: `${widthPct}%` }}
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 4: AGENCY BACKLOG & AGEING TIERS                      */}
      {/* ========================================================= */}
      {activeTab === 'backlog' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div>
            <h2 className="text-lg font-bold text-white">Agency Workload &amp; Backlog Ageing Profile</h2>
            <p className="text-xs text-slate-400">Open work orders broken down into 4 ageing brackets.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {backlogData.map((b, idx) => (
              <div key={idx} className="bg-slate-800/60 border border-slate-700/60 rounded-2xl p-5 shadow-lg space-y-3">
                <div className="font-extrabold text-white text-base">{b.agency}</div>
                <div className="text-3xl font-black text-indigo-400">{b.total_backlog} <span className="text-xs text-slate-400 font-normal">open requests</span></div>
                
                <div className="space-y-1.5 text-xs pt-2 border-t border-slate-700">
                  <div className="flex justify-between text-slate-300"><span>&lt; 7 Days:</span> <strong className="text-emerald-400">{b.backlog_under_7d}</strong></div>
                  <div className="flex justify-between text-slate-300"><span>7 - 30 Days:</span> <strong className="text-amber-400">{b.backlog_7_to_30d}</strong></div>
                  <div className="flex justify-between text-slate-300"><span>31 - 90 Days:</span> <strong className="text-orange-400">{b.backlog_31_to_90d}</strong></div>
                  <div className="flex justify-between text-slate-300"><span>&gt; 90 Days:</span> <strong className="text-rose-400">{b.backlog_over_90d}</strong></div>
                  <div className="flex justify-between text-slate-400 pt-1"><span>Avg Backlog Age:</span> <span>{b.avg_age_days} days</span></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 5: DATA QUALITY FIREWALL & QUARANTINE DLQ             */}
      {/* ========================================================= */}
      {activeTab === 'quarantine' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold text-white">Data Quality Firewall &amp; Dead-Letter Queue (DLQ)</h2>
              <p className="text-xs text-slate-400">All incoming payloads are screened against identity, temporal paradox, and geospatial rules.</p>
            </div>
            <span className="bg-rose-500/20 text-rose-400 border border-rose-500/30 text-xs font-bold px-3 py-1 rounded-full">
              {quarantineData.total_quarantined} Quarantined Payloads
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Object.entries(quarantineData.reasons_breakdown || {}).map(([reason, count], idx) => (
              <div key={idx} className="bg-rose-950/20 border border-rose-900/40 rounded-xl p-4">
                <div className="text-xs font-bold text-rose-400">{reason}</div>
                <div className="text-2xl font-black text-white mt-1">{count} <span className="text-xs text-slate-400 font-normal">rejected</span></div>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border border-slate-800 rounded-xl overflow-hidden">
              <thead className="bg-slate-800 text-slate-400 uppercase font-bold text-[11px]">
                <tr>
                  <th className="p-3">Service Request ID</th>
                  <th className="p-3">Primary Rejection Reason</th>
                  <th className="p-3">Quarantined At</th>
                  <th className="p-3">Batch ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-slate-300">
                {(quarantineData.sample_records || []).map((row, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    <td className="p-3 font-mono font-bold text-indigo-400">{row.service_request_id || '<null-id>'}</td>
                    <td className="p-3 text-rose-400 font-semibold">{row.rejection_reason}</td>
                    <td className="p-3 font-mono">{row.quarantined_at ? row.quarantined_at.substring(0, 19) : ''}</td>
                    <td className="p-3 font-mono text-slate-500">{row.source_batch_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="text-center text-xs text-slate-500 pt-6 pb-2 border-t border-slate-800/80">
        CivicPulse Public Infrastructure Intelligence &bull; React &bull; Leaflet &bull; FastAPI &bull; DuckDB Lakehouse
      </footer>

    </div>
  );
}

// Mount React Root
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
