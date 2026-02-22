/**
 * Workflow Constants - Centralized status and configuration constants
 * 
 * This module provides a single source of truth for workflow statuses,
 * events, and document types used across the frontend.
 */

// Document Types supported by the system
export const DOC_TYPES = {
  AP_INVOICE: 'AP_INVOICE',
  SALES_INVOICE: 'SALES_INVOICE',
  PURCHASE_ORDER: 'PURCHASE_ORDER',
  SALES_CREDIT_MEMO: 'SALES_CREDIT_MEMO',
  PURCHASE_CREDIT_MEMO: 'PURCHASE_CREDIT_MEMO',
  STATEMENT: 'STATEMENT',
  REMINDER: 'REMINDER',
  FINANCE_CHARGE_MEMO: 'FINANCE_CHARGE_MEMO',
  QUALITY_DOC: 'QUALITY_DOC',
  OTHER: 'OTHER',
};

// Source Systems
export const SOURCE_SYSTEMS = {
  SQUARE9: 'SQUARE9',
  ZETADOCS: 'ZETADOCS',
  GPI_HUB_NATIVE: 'GPI_HUB_NATIVE',
  MIGRATION: 'MIGRATION',
  UNKNOWN: 'UNKNOWN',
};

export const SOURCE_SYSTEM_LABELS = {
  SQUARE9: 'Square9',
  ZETADOCS: 'Zetadocs',
  GPI_HUB_NATIVE: 'GPI Hub',
  MIGRATION: 'Migration',
  UNKNOWN: 'Unknown',
};

// AP Invoice workflow statuses
export const AP_WORKFLOW_STATUSES = {
  CAPTURED: 'captured',
  CLASSIFIED: 'classified',
  EXTRACTED: 'extracted',
  VENDOR_PENDING: 'vendor_pending',
  BC_VALIDATION_PENDING: 'bc_validation_pending',
  BC_VALIDATION_FAILED: 'bc_validation_failed',
  DATA_CORRECTION_PENDING: 'data_correction_pending',
  READY_FOR_APPROVAL: 'ready_for_approval',
  APPROVAL_IN_PROGRESS: 'approval_in_progress',
  APPROVED: 'approved',
  REJECTED: 'rejected',
  EXPORTED: 'exported',
  ARCHIVED: 'archived',
};

// AP Workflow Queue definitions with their display configuration
export const AP_QUEUE_CONFIG = {
  [AP_WORKFLOW_STATUSES.VENDOR_PENDING]: {
    label: 'Vendor Pending',
    shortLabel: 'Vendor',
    description: 'Awaiting vendor match',
    color: 'bg-yellow-500',
    textColor: 'text-yellow-500',
    actions: ['set-vendor'],
    isActiveQueue: true,
  },
  [AP_WORKFLOW_STATUSES.BC_VALIDATION_PENDING]: {
    label: 'BC Validation',
    shortLabel: 'BC Valid.',
    description: 'Validating in Business Central',
    color: 'bg-blue-500',
    textColor: 'text-blue-500',
    actions: [],
    isActiveQueue: true,
  },
  [AP_WORKFLOW_STATUSES.BC_VALIDATION_FAILED]: {
    label: 'Validation Failed',
    shortLabel: 'Failed',
    description: 'BC validation errors',
    color: 'bg-red-500',
    textColor: 'text-red-500',
    actions: ['override-bc-validation'],
    isActiveQueue: true,
  },
  [AP_WORKFLOW_STATUSES.DATA_CORRECTION_PENDING]: {
    label: 'Data Correction',
    shortLabel: 'Correction',
    description: 'Needs manual data fix',
    color: 'bg-orange-500',
    textColor: 'text-orange-500',
    actions: ['update-fields'],
    isActiveQueue: true,
  },
  [AP_WORKFLOW_STATUSES.READY_FOR_APPROVAL]: {
    label: 'Ready for Approval',
    shortLabel: 'Ready',
    description: 'Awaiting approval',
    color: 'bg-green-500',
    textColor: 'text-green-500',
    actions: ['start-approval', 'approve', 'reject'],
    isActiveQueue: true,
  },
  [AP_WORKFLOW_STATUSES.APPROVAL_IN_PROGRESS]: {
    label: 'Approval In Progress',
    shortLabel: 'In Progress',
    description: 'Being reviewed',
    color: 'bg-purple-500',
    textColor: 'text-purple-500',
    actions: ['approve', 'reject'],
    isActiveQueue: true,
  },
  [AP_WORKFLOW_STATUSES.APPROVED]: {
    label: 'Approved',
    shortLabel: 'Approved',
    description: 'Approved and ready',
    color: 'bg-emerald-500',
    textColor: 'text-emerald-500',
    actions: ['export'],
    isActiveQueue: false,
  },
  [AP_WORKFLOW_STATUSES.EXPORTED]: {
    label: 'Exported',
    shortLabel: 'Exported',
    description: 'Exported to BC',
    color: 'bg-slate-500',
    textColor: 'text-slate-400',
    actions: [],
    isActiveQueue: false,
  },
  [AP_WORKFLOW_STATUSES.REJECTED]: {
    label: 'Rejected',
    shortLabel: 'Rejected',
    description: 'Rejected',
    color: 'bg-red-700',
    textColor: 'text-red-400',
    actions: [],
    isActiveQueue: false,
  },
};

// Define which statuses constitute "active" queues that need attention
export const AP_ACTIVE_QUEUE_STATUSES = Object.entries(AP_QUEUE_CONFIG)
  .filter(([_, config]) => config.isActiveQueue)
  .map(([status]) => status);

// Primary AP queues to display in the main workflow view
export const AP_PRIMARY_QUEUES = [
  AP_WORKFLOW_STATUSES.VENDOR_PENDING,
  AP_WORKFLOW_STATUSES.BC_VALIDATION_PENDING,
  AP_WORKFLOW_STATUSES.BC_VALIDATION_FAILED,
  AP_WORKFLOW_STATUSES.READY_FOR_APPROVAL,
  AP_WORKFLOW_STATUSES.APPROVAL_IN_PROGRESS,
];

// Secondary AP queues (for history/archive views)
export const AP_SECONDARY_QUEUES = [
  AP_WORKFLOW_STATUSES.APPROVED,
  AP_WORKFLOW_STATUSES.EXPORTED,
  AP_WORKFLOW_STATUSES.REJECTED,
];

// Get config for any status with fallback
export function getQueueConfig(status) {
  return AP_QUEUE_CONFIG[status] || {
    label: status,
    shortLabel: status,
    description: '',
    color: 'bg-gray-500',
    textColor: 'text-gray-500',
    actions: [],
    isActiveQueue: false,
  };
}

// Format currency for display
export function formatCurrency(amount, currency = 'USD') {
  if (amount == null) return '-';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency,
    minimumFractionDigits: 2,
  }).format(amount);
}

// Format date for display
export function formatDate(dateStr) {
  if (!dateStr) return '-';
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch {
    return dateStr;
  }
}

// Calculate age in days from a date string
export function calculateAgeDays(dateStr) {
  if (!dateStr) return null;
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    return Math.floor(diffMs / (1000 * 60 * 60 * 24));
  } catch {
    return null;
  }
}
