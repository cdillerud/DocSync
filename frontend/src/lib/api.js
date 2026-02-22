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
export const getDashboardStats = () => api.get('/dashboard/stats');

// Documents
export const uploadDocument = (formData) => api.post('/documents/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
export const listDocuments = (params) => api.get('/documents', { params });
export const getDocument = (id) => api.get(`/documents/${id}`);
export const updateDocument = (id, data) => api.put(`/documents/${id}`, data);
export const linkDocument = (id) => api.post(`/documents/${id}/link`);
export const deleteDocument = (id) => api.delete(`/documents/${id}`);
export const resubmitDocument = (id) => api.post(`/documents/${id}/reprocess?reclassify=true`);

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

// AP Invoice Workflow Actions
export const setVendor = (docId, vendorNo, vendorName, actor) => api.post(`/workflows/ap_invoice/${docId}/set-vendor`, { vendor_no: vendorNo, vendor_name: vendorName, actor });
export const updateFields = (docId, fields, actor) => api.post(`/workflows/ap_invoice/${docId}/update-fields`, { ...fields, actor });
export const overrideBcValidation = (docId, reason, actor) => api.post(`/workflows/ap_invoice/${docId}/override-bc-validation`, { reason, actor });
export const startApproval = (docId, actor) => api.post(`/workflows/ap_invoice/${docId}/start-approval`, { actor });
export const approveDocument = (docId, comment, actor) => api.post(`/workflows/ap_invoice/${docId}/approve`, { comment, actor });
export const rejectDocument = (docId, reason, actor) => api.post(`/workflows/ap_invoice/${docId}/reject`, { reason, actor });

export default api;
