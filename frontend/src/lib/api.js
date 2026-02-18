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
export const resubmitDocument = (id) => api.post(`/documents/${id}/resubmit`);

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

// Email Watcher Config
export const getEmailWatcherConfig = () => api.get('/settings/email-watcher');
export const updateEmailWatcherConfig = (data) => api.put('/settings/email-watcher', data);
export const subscribeEmailWatcher = (webhookUrl) => api.post(`/settings/email-watcher/subscribe?webhook_url=${encodeURIComponent(webhookUrl)}`);

// Email Stats Dashboard
export const getEmailStats = () => api.get('/dashboard/email-stats');

// Document Intake & Classification
export const intakeDocument = (formData) => api.post('/documents/intake', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
export const classifyDocument = (id) => api.post(`/documents/${id}/classify`);

export default api;
