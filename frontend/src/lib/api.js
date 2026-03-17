import axios from 'axios';

const API_BASE = `${process.env.REACT_APP_BACKEND_URL}/api`;

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('gpi_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('gpi_token');
      localStorage.removeItem('gpi_user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Auth
export const login = (username, password) => api.post('/auth/login', { username, password });
export const getMe = () => api.get('/auth/me');

// Dashboard
export const getDashboardStats = (date) => api.get('/dashboard/stats', { params: date ? { date } : {} });
export const getDocumentTypesDashboard = (params) => api.get('/dashboard/document-types', { params });
export const getWorkflowIntelligence = (date) => api.get('/dashboard/workflow-intelligence', { params: date ? { date } : {} });
export const exportDocumentTypesDashboard = (params) => {
  const queryString = new URLSearchParams(
    Object.entries(params || {}).filter(([_, v]) => v !== null && v !== undefined && v !== 'all')
  ).toString();
  const url = `${API_BASE_URL}/dashboard/document-types/export${queryString ? '?' + queryString : ''}`;
  window.location.href = url;
};

// Documents
export const uploadDocument = (formData) => api.post('/documents/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
export const listDocuments = (params) => api.get('/documents', { params });
export const getDocument = (id, includeEvents = true) => api.get(`/documents/${id}`, { params: { include_events: includeEvents } });
export const updateDocument = (id, data) => api.put(`/documents/${id}`, data);
export const linkDocument = (id) => api.post(`/documents/${id}/link`);
export const deleteDocument = (id) => api.delete(`/documents/${id}`);
export const resubmitDocument = (id) => api.post(`/documents/${id}/reprocess?reclassify=true`);

// Event-Driven Workflow APIs
export const getDocumentEvents = (id, params) => api.get(`/documents/${id}/events`, { params });
export const getDocumentTimeline = (id, includeLegacy = true) => api.get(`/documents/${id}/timeline`, { params: { include_legacy: includeLegacy } });
export const getDocumentDerivedState = (id) => api.get(`/documents/${id}/derived-state`);
export const refreshDocumentState = (id) => api.post(`/documents/${id}/refresh-state`);
export const getEventTypes = () => api.get('/events/types');
export const getRecentEvents = (params) => api.get('/events/recent', { params });
export const getEventStats = (sinceHours = 24) => api.get('/events/stats', { params: { since_hours: sinceHours } });

// BC Reference Resolution + Write Safety APIs
export const resolveBCReference = (referenceNumber) => api.post('/bc/resolve-reference', null, { params: { reference_number: referenceNumber } });
export const resolveDocumentReference = (docId) => api.post(`/documents/${docId}/resolve-reference`);
export const resolveDocumentIntelligence = (docId) => api.post(`/documents/${docId}/resolve-intelligence`);
export const getDocumentReferenceIntelligence = (docId) => api.get(`/documents/${docId}/reference-intelligence`);
export const getBCWriteGuardStatus = () => api.get('/bc/write-guard/status');
export const checkBCWritePermission = (documentId, action) => api.post('/bc/write-guard/check', null, { params: { document_id: documentId, action } });

// BC Reference Cache APIs
export const getCacheStatus = () => api.get('/cache/status');
export const triggerCacheSync = (mode = 'incremental') => api.post('/cache/sync', null, { params: { mode } });
export const searchCache = (reference, entityType = null) => {
  const params = { reference };
  if (entityType) params.entity_type = entityType;
  return api.get('/cache/search', { params });
};

// Square9 Workflow Retry
export const retryDocument = (id, reason = 'Manual retry') => api.post(`/documents/${id}/retry?reason=${encodeURIComponent(reason)}`);
export const resetDocumentRetries = (id, reason = 'Manual reset') => api.post(`/documents/${id}/reset-retries?reason=${encodeURIComponent(reason)}`);
export const getSquare9Status = (id) => api.get(`/documents/${id}/square9-status`);
export const getSquare9StageCounts = () => api.get('/square9/stage-counts');

// Automation Rules APIs
export const listAutomationRules = () => api.get('/automation-rules');
export const createAutomationRule = (rule) => api.post('/automation-rules', rule);
export const updateAutomationRule = (ruleId, updates) => api.put(`/automation-rules/${ruleId}`, updates);
export const deleteAutomationRule = (ruleId) => api.delete(`/automation-rules/${ruleId}`);
export const toggleAutomationRule = (ruleId) => api.post(`/automation-rules/${ruleId}/toggle`);
export const getRuleSuggestions = () => api.get('/automation-rules/suggestions');
export const evaluateRulesForDoc = (docId) => api.post(`/automation-rules/evaluate/${docId}`);

// Stable Vendor APIs
export const getStableVendorMetrics = () => api.get('/stable-vendor/dashboard-metrics');
export const evaluateDocumentRouting = (docId) => api.post(`/stable-vendor/evaluate-document/${docId}`);
export const evaluateVendorStability = (vendorId) => api.get(`/stable-vendor/evaluate/${vendorId}`);
export const reevaluateAllVendors = () => api.post('/stable-vendor/reevaluate-all');

// Stable Vendor Admin APIs
export const getStableVendors = (params) => api.get('/stable-vendor/vendors', { params });
export const getStableVendorDetail = (vendorNo) => api.get(`/stable-vendor/vendors/${encodeURIComponent(vendorNo)}`);
export const applyVendorOverride = (vendorNo, data) => api.post(`/stable-vendor/vendors/${encodeURIComponent(vendorNo)}/override`, data);
export const clearVendorOverride = (vendorNo, data) => api.post(`/stable-vendor/vendors/${encodeURIComponent(vendorNo)}/clear-override`, data);
export const getVendorOverrideHistory = (vendorNo) => api.get(`/stable-vendor/vendors/${encodeURIComponent(vendorNo)}/history`);

// Stable Vendor Config & Diagnostics
export const getStableVendorConfig = () => api.get('/stable-vendor/config');
export const getDailyIngestion = (date) => api.get('/dashboard/daily-ingestion', { params: date ? { date } : {} });
export const updateStableVendorConfig = (data) => api.put('/stable-vendor/config', data);
export const diagnoseStableVendors = () => api.get('/stable-vendor/diagnose');
export const applySuggestedThresholds = () => api.post('/stable-vendor/apply-suggested-thresholds');

// Auto-Approve
export const diagnoseApprovalBacklog = () => api.get('/auto-approve/diagnose');
export const dryRunAutoApprove = (params) => api.post('/auto-approve/dry-run', null, { params });
export const runAutoApprove = (params) => api.post('/auto-approve/run', null, { params });

// Bulk operations
export const bulkRetryDocuments = async (docIds, reason = 'Bulk retry') => {
  const results = { success: [], failed: [] };
  for (const id of docIds) {
    try {
      const res = await retryDocument(id, reason);
      results.success.push({ id, data: res.data });
    } catch (err) {
      results.failed.push({ id, error: err.response?.data?.detail || err.message });
    }
  }
  return results;
};

export const bulkResubmitDocuments = async (docIds) => {
  const results = { success: [], failed: [] };
  for (const id of docIds) {
    try {
      const res = await resubmitDocument(id);
      results.success.push({ id, data: res.data });
    } catch (err) {
      results.failed.push({ id, error: err.response?.data?.detail || err.message });
    }
  }
  return results;
};

export const bulkDeleteDocuments = async (docIds) => {
  const results = { success: [], failed: [] };
  for (const id of docIds) {
    try {
      await deleteDocument(id);
      results.success.push({ id });
    } catch (err) {
      results.failed.push({ id, error: err.response?.data?.detail || err.message });
    }
  }
  return results;
};

// File & Clear
export const fileAndClearDocument = (docId) => api.post(`/documents/${docId}/file-and-clear`);
export const bulkFileAndClear = (docIds) => api.post('/documents/bulk-file-and-clear', docIds);
export const bulkApproveAndFile = (category, limit = 500) => api.post(`/documents/bulk-approve-and-file?category=${category || 'needs_approval'}&limit=${limit}`);
export const getFilingStats = () => api.get('/documents/filing-actions/stats');

// Workflows
export const listWorkflows = (params) => api.get('/workflows', { params });
export const getWorkflow = (id) => api.get(`/workflows/${id}`);
export const retryWorkflow = (id) => api.post(`/workflows/${id}/retry`);

// BC Proxy
export const getBcCompanies = () => api.get('/bc/companies');
export const getBcSalesOrders = (search) => api.get('/bc/sales-orders', { params: { search } });

// Settings
export const getSettingsStatus = () => api.get('/settings/status');
export const getSettingsConfig = () => api.get('/settings/config');
export const updateSettingsConfig = (data) => api.put('/settings/config', data);
export const testConnection = (service) => api.post(`/settings/test-connection?service=${service}`);

// Job Types (Email Parser Config)
export const getJobTypes = () => api.get('/settings/job-types');
export const getJobType = (jobType) => api.get(`/settings/job-types/${jobType}`);
export const updateJobType = (jobType, data) => api.put(`/settings/job-types/${jobType}`, data);

// Email Watcher Config (Legacy)
export const getEmailWatcherConfig = () => api.get('/settings/email-watcher');
export const updateEmailWatcherConfig = (data) => api.put('/settings/email-watcher', data);
export const subscribeEmailWatcher = (webhookUrl) => api.post(`/settings/email-watcher/subscribe?webhook_url=${encodeURIComponent(webhookUrl)}`);

// Mailbox Sources CRUD
export const listMailboxSources = () => api.get('/settings/mailbox-sources');
export const getMailboxSource = (id) => api.get(`/settings/mailbox-sources/${id}`);
export const createMailboxSource = (data) => api.post('/settings/mailbox-sources', data);
export const updateMailboxSource = (id, data) => api.put(`/settings/mailbox-sources/${id}`, data);
export const deleteMailboxSource = (id) => api.delete(`/settings/mailbox-sources/${id}`);
export const testMailboxConnection = (id) => api.post(`/settings/mailbox-sources/${id}/test-connection`);
export const pollMailboxNow = (id) => api.post(`/settings/mailbox-sources/${id}/poll-now`);
export const getMailboxPollingStatus = () => api.get('/settings/mailbox-sources/polling-status');

// Email Stats Dashboard
export const getEmailStats = () => api.get('/dashboard/email-stats');

// Document Intake & Classification
export const intakeDocument = (formData) => api.post('/documents/intake', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
export const classifyDocument = (id) => api.post(`/documents/${id}/classify`);

// AP Invoice Workflow Queues
export const getWorkflowStatusCounts = () => api.get('/workflows/ap_invoice/status-counts');
export const getVendorPendingQueue = (params) => api.get('/workflows/ap_invoice/vendor-pending', { params });
export const getBcValidationPendingQueue = (params) => api.get('/workflows/ap_invoice/bc-validation-pending', { params });
export const getBcValidationFailedQueue = (params) => api.get('/workflows/ap_invoice/bc-validation-failed', { params });
export const getDataCorrectionPendingQueue = (params) => api.get('/workflows/ap_invoice/data-correction-pending', { params });
export const getReadyForApprovalQueue = (params) => api.get('/workflows/ap_invoice/ready-for-approval', { params });
export const getWorkflowMetrics = (days) => api.get('/workflows/ap_invoice/metrics', { params: { days } });

// Generic Workflow APIs (multi-document type support)
export const getGenericQueue = (docType, params) => api.get('/workflows/generic/queue', { params: { doc_type: docType, ...params } });
export const getStatusCountsByType = () => api.get('/workflows/generic/status-counts-by-type');
export const getMetricsByType = (days, docType) => api.get('/workflows/generic/metrics-by-type', { params: { days, doc_type: docType } });

// AP Invoice Workflow Actions
export const setVendor = (docId, vendorNo, vendorName, actor) => api.post(`/workflows/ap_invoice/${docId}/set-vendor`, { vendor_no: vendorNo, vendor_name: vendorName, actor });
export const updateFields = (docId, fields, actor) => api.post(`/workflows/ap_invoice/${docId}/update-fields`, { ...fields, actor });
export const overrideBcValidation = (docId, reason, actor) => api.post(`/workflows/ap_invoice/${docId}/override-bc-validation`, { reason, actor });
export const startApproval = (docId, actor) => api.post(`/workflows/ap_invoice/${docId}/start-approval`, { actor });
export const approveDocument = (docId, comment, actor) => api.post(`/workflows/ap_invoice/${docId}/approve`, { comment, actor });
export const rejectDocument = (docId, reason, actor) => api.post(`/workflows/ap_invoice/${docId}/reject`, { reason, actor });

// Generic Workflow Actions (for any doc type)
export const exportDocument = (docId, destination, user) => api.post(`/workflows/${docId}/export`, null, { params: { export_destination: destination, user } });

// Get AP Dashboard metrics (from doc-types dashboard filtered to AP)
export const getAPDashboardMetrics = () => api.get('/dashboard/document-types', { params: { doc_type: 'AP_INVOICE' } });

// =============================================================================
// PILOT APIs
// =============================================================================

// Get pilot status and configuration
export const getPilotStatus = () => api.get('/pilot/status');

// Get pilot daily metrics
export const getPilotDailyMetrics = (phase = 'shadow_pilot_v1', date = null) => 
  api.get('/pilot/daily-metrics', { params: { phase, date } });

// Get pilot logs
export const getPilotLogs = (params = {}) => 
  api.get('/pilot/logs', { params: { phase: 'shadow_pilot_v1', ...params } });

// Get pilot accuracy report
export const getPilotAccuracy = (phase = 'shadow_pilot_v1') => 
  api.get('/pilot/accuracy', { params: { phase } });

// Get pilot trend data
export const getPilotTrend = (phase = 'shadow_pilot_v1', days = 14) => 
  api.get('/pilot/trend', { params: { phase, days } });

// Send daily pilot summary email manually
export const sendPilotSummaryEmail = () => 
  api.post('/pilot/send-daily-summary');

// Get pilot email logs
export const getPilotEmailLogs = (limit = 20, skip = 0) =>
  api.get('/pilot/email-logs', { params: { limit, skip } });

// Get pilot email config
export const getPilotEmailConfig = () =>
  api.get('/pilot/email-config');

// =============================================================================
// AP REVIEW APIs
// =============================================================================

// Search vendors from BC
export const searchVendors = (query = '', limit = 50) => 
  api.get('/ap-review/vendors', { params: { q: query, limit } });

// Get vendor by ID
export const getVendor = (vendorId) => 
  api.get(`/ap-review/vendors/${vendorId}`);

// Search purchase orders from BC
export const searchPurchaseOrders = (vendorId = null, limit = 50) => 
  api.get('/ap-review/purchase-orders', { params: { vendor_id: vendorId, limit } });

// Save AP review edits
export const saveAPReview = (docId, data) => 
  api.put(`/ap-review/documents/${docId}`, data);

// Mark document ready for posting
export const markReadyForPost = (docId) => 
  api.post(`/ap-review/documents/${docId}/mark-ready`);

// Post document to BC
export const postToBC = (docId, data = null) => 
  api.post(`/ap-review/documents/${docId}/post-to-bc`, data);

// Get BC posting status
export const getBCPostingStatus = (docId) => 
  api.get(`/ap-review/documents/${docId}/bc-status`);

// Extract invoice data using AI
export const extractInvoiceData = (docId) => 
  api.post(`/ap-review/documents/${docId}/extract-invoice-data`);

// Get extraction status
export const getExtractionStatus = (docId) => 
  api.get(`/ap-review/documents/${docId}/extraction-status`);

// =============================================================================
// GPI INTEGRATION APIs (BC Sales Order creation)
// =============================================================================

// Get GPI Integration status
export const getGPIIntegrationStatus = () => api.get('/gpi-integration/status');

// Preflight validation for BC Sales Order creation
export const salesOrderPreflight = (docId) => api.post(`/gpi-integration/sales-orders/preflight/${docId}`);

// Create BC Sales Order from document with user-edited lines
export const createSalesOrderFromDocument = (docId, { customerNoOverride = '', editedLines = null, inventoryWorkspaceId = '' } = {}) => {
  return api.post(`/gpi-integration/sales-orders/from-document/${docId}`, {
    customer_no_override: customerNoOverride,
    edited_lines: editedLines,
    inventory_workspace_id: inventoryWorkspaceId,
  });
};

// Preflight validation for BC Purchase Invoice creation
export const purchaseInvoicePreflight = (docId) => api.post(`/gpi-integration/purchase-invoices/preflight/${docId}`);

// Create BC Purchase Invoice from document
export const createPurchaseInvoiceFromDocument = (docId, vendorNoOverride = '') => {
  const params = vendorNoOverride ? { vendor_no_override: vendorNoOverride } : {};
  return api.post(`/gpi-integration/purchase-invoices/from-document/${docId}`, null, { params });
};

export default api;

// Create incoming supply from shortage lines
export const createIncomingFromShortage = (salesOrderId, lines) => {
  return api.post('/incoming-supply/from-shortage', {
    sales_order_id: salesOrderId,
    lines,
  });
};

// Reconcile SO commitments after edit or cancel
export const reconcileSalesOrder = (salesOrderId, lines, cancelled = false) => {
  return api.post('/inventory-ledger/reconcile-sales-order', {
    sales_order_id: salesOrderId,
    lines,
    cancelled,
  });
};


// Document Intelligence
export const processDocumentIntelligence = (docId) => api.post(`/document-intelligence/process/${docId}`);
export const getDocumentIntelligence = (docId) => api.get(`/document-intelligence/${docId}`);
export const getIntelligenceReviewQueue = (params) => api.get('/document-intelligence/review-queue', { params });
export const correctDocumentIntelligence = (docId, data) => api.patch(`/document-intelligence/${docId}`, data);
export const getIntelligenceSummary = () => api.get('/document-intelligence/summary');
export const createAutoDraft = (docId) => api.post(`/document-intelligence/auto-draft/${docId}`);
export const getAutomationAction = (docId) => api.get(`/document-intelligence/auto-draft/${docId}`);
export const resolveDocumentEntities = (docId) => api.post(`/document-intelligence/resolve-entities/${docId}`);
export const getDocumentResolutions = (docId) => api.get(`/document-intelligence/resolution/${docId}`);
export const correctResolution = (resolutionId, data) => api.patch(`/document-intelligence/resolution/${resolutionId}`, data);
export const matchTransactions = (docId) => api.post(`/document-intelligence/match-transactions/${docId}`);
export const getTransactionMatches = (docId) => api.get(`/document-intelligence/transaction-matches/${docId}`);
export const autoLinkDocument = (docId) => api.post(`/document-intelligence/auto-link/${docId}`);
export const confirmTransactionMatch = (matchId, data) => api.patch(`/document-intelligence/transaction-matches/${matchId}`, data);

// Document Bundle APIs
export const detectBundles = (data) => api.post('/document-intelligence/detect-bundles', data || {});
export const listBundles = (params) => api.get('/document-intelligence/bundles', { params });
export const getBundle = (bundleId) => api.get(`/document-intelligence/bundles/${bundleId}`);
export const updateBundle = (bundleId, data) => api.patch(`/document-intelligence/bundles/${bundleId}`, data);
export const getBundleReviewQueue = (params) => api.get('/document-intelligence/bundle-review-queue', { params });

// Document Lifecycle APIs
export const validateLifecycle = (entityType, entityId) => api.post(`/document-intelligence/validate-lifecycle/${entityType}/${entityId}`);
export const getLifecycle = (entityType, entityId) => api.get(`/document-intelligence/lifecycle/${entityType}/${entityId}`);
export const getLifecycleIssues = (params) => api.get('/document-intelligence/lifecycle-issues', { params });

// Decision Policy APIs
export const createPolicy = (data) => api.post('/document-intelligence/policies', data);
export const listPolicies = (params) => api.get('/document-intelligence/policies', { params });
export const updatePolicy = (policyId, data) => api.patch(`/document-intelligence/policies/${policyId}`, data);
export const deletePolicy = (policyId) => api.delete(`/document-intelligence/policies/${policyId}`);
export const evaluateDecision = (docId) => api.post(`/document-intelligence/evaluate-decision/${docId}`);
export const executeDecision = (decisionId) => api.post(`/document-intelligence/execute-decision/${decisionId}`);
export const getDecision = (docId) => api.get(`/document-intelligence/decision/${docId}`);
export const getDecisionQueue = (params) => api.get('/document-intelligence/decision-queue', { params });

// Learning Loop APIs
export const getLearningEvents = (params) => api.get('/document-intelligence/learning/events', { params });
export const getLearningSummary = () => api.get('/document-intelligence/learning/summary');
export const getDocumentLearningEvents = (docId) => api.get(`/document-intelligence/learning/events/${docId}`);

// SharePoint Routing APIs
export const getSharePointFolderTree = () => api.get('/sharepoint-routing/folder-tree');
export const getSharePointFolderRules = (includeInactive) => api.get('/sharepoint-routing/folder-rules', { params: { include_inactive: includeInactive } });
export const createFolderRule = (rule) => api.post('/sharepoint-routing/folder-rules', rule);
export const updateFolderRule = (key, data) => api.put(`/sharepoint-routing/folder-rules/${key}`, data);
export const deleteFolderRule = (key) => api.delete(`/sharepoint-routing/folder-rules/${key}`);
export const getVendorMappings = () => api.get('/sharepoint-routing/vendor-mappings');
export const createVendorMapping = (mapping) => api.post('/sharepoint-routing/vendor-mappings', mapping);
export const deleteVendorMapping = (pattern) => api.delete(`/sharepoint-routing/vendor-mappings/${encodeURIComponent(pattern)}`);
export const getProcessorAssignments = () => api.get('/sharepoint-routing/processor-assignments');
export const createProcessorAssignment = (assignment) => api.post('/sharepoint-routing/processor-assignments', assignment);
export const suggestFolder = (data) => api.post('/sharepoint-routing/suggest-folder', data);
export const getDocSuggestedFolder = (docId) => api.get(`/sharepoint-routing/document/${docId}/suggested-folder`);
export const assignFolderToDoc = (docId, folder) => api.post(`/sharepoint-routing/document/${docId}/assign-folder`, { folder_path: folder });
export const moveDocToSharePoint = (docId) => api.post(`/sharepoint-routing/document/${docId}/move-to-sharepoint`);
export const batchMoveToSharePoint = (docIds) => api.post('/sharepoint-routing/batch-move', { doc_ids: docIds });
export const batchSuggestFolders = (data) => api.post('/sharepoint-routing/batch-suggest', data);
export const seedSharePointDefaults = () => api.post('/sharepoint-routing/seed-defaults');

// AR Release Gate APIs
export const getARReleaseMetrics = () => api.get('/ar-release/metrics');
export const evaluateARRelease = (docId) => api.post(`/ar-release/evaluate/${docId}`);
export const overrideARRelease = (docId, data) => api.post(`/ar-release/override/${docId}`, data);
export const getARReleaseQueue = (params) => api.get('/ar-release/queue', { params });

// Automation Intelligence APIs
export const getAutomationMetrics = () => api.get('/automation/metrics');
export const batchEvaluateIntelligence = (limit) => api.post(`/automation/batch-evaluate?limit=${limit || 200}`);
export const getDecisionExplanation = (docId) => api.get(`/documents/${docId}/decision-explanation`);
export const getAutomationConfidence = (docId) => api.get(`/documents/${docId}/automation-confidence`);
export const getReviewAssist = (docId) => api.post(`/documents/${docId}/review-assist`);
export const acceptSuggestion = (docId, data) => api.post(`/documents/${docId}/accept-suggestion`, data);




