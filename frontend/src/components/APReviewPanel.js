import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Badge } from './ui/badge';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from './ui/select';
import { toast } from 'sonner';
import { 
  Save, Send, Search, Building2, FileText, 
  Package, DollarSign, Calendar, Hash, Loader2,
  CheckCircle2, AlertCircle, Plus, Trash2
} from 'lucide-react';
import { 
  searchVendors, 
  searchPurchaseOrders, 
  saveAPReview, 
  markReadyForPost, 
  postToBC 
} from '../lib/api';

const CURRENCIES = ['USD', 'CAD', 'EUR', 'GBP', 'MXN'];

export function APReviewPanel({ document, onUpdate }) {
  // Form state
  const [formData, setFormData] = useState({
    vendor_id: '',
    vendor_name_resolved: '',
    invoice_number: '',
    invoice_date: '',
    due_date: '',
    currency: 'USD',
    total_amount: '',
    tax_amount: '',
    po_number: '',
    line_items: []
  });
  
  // Search states
  const [vendorSearch, setVendorSearch] = useState('');
  const [vendorResults, setVendorResults] = useState([]);
  const [vendorLoading, setVendorLoading] = useState(false);
  const [showVendorDropdown, setShowVendorDropdown] = useState(false);
  
  const [poSearch, setPoSearch] = useState('');
  const [poResults, setPoResults] = useState([]);
  const [poLoading, setPoLoading] = useState(false);
  const [showPoDropdown, setShowPoDropdown] = useState(false);
  
  // Action states
  const [saving, setSaving] = useState(false);
  const [posting, setPosting] = useState(false);
  const [markingReady, setMarkingReady] = useState(false);
  
  // Initialize form from document
  useEffect(() => {
    if (document) {
      const extracted = document.extracted_fields || {};
      setFormData({
        vendor_id: document.vendor_id || document.vendor_canonical || '',
        vendor_name_resolved: document.vendor_name_resolved || document.vendor_raw || extracted.vendor || '',
        invoice_number: document.invoice_number_clean || extracted.invoice_number || '',
        invoice_date: document.invoice_date || extracted.invoice_date || '',
        due_date: document.due_date_iso || extracted.due_date || '',
        currency: document.currency || 'USD',
        total_amount: document.amount_float || extracted.amount || '',
        tax_amount: document.tax_amount || '',
        po_number: document.po_number_clean || extracted.po_number || '',
        line_items: document.line_items || []
      });
      setVendorSearch(document.vendor_name_resolved || document.vendor_raw || extracted.vendor || '');
    }
  }, [document]);
  
  // Vendor search
  const handleVendorSearch = useCallback(async (query) => {
    if (!query || query.length < 2) {
      setVendorResults([]);
      return;
    }
    
    setVendorLoading(true);
    try {
      const res = await searchVendors(query, 20);
      setVendorResults(res.data.vendors || []);
      setShowVendorDropdown(true);
    } catch (err) {
      console.error('Vendor search error:', err);
      toast.error('Failed to search vendors');
    } finally {
      setVendorLoading(false);
    }
  }, []);
  
  // Debounce vendor search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (vendorSearch && vendorSearch !== formData.vendor_name_resolved) {
        handleVendorSearch(vendorSearch);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [vendorSearch, formData.vendor_name_resolved, handleVendorSearch]);
  
  // PO search
  const handlePoSearch = useCallback(async () => {
    setPoLoading(true);
    try {
      const res = await searchPurchaseOrders(formData.vendor_id, 20);
      setPoResults(res.data.purchaseOrders || []);
      setShowPoDropdown(true);
    } catch (err) {
      console.error('PO search error:', err);
      toast.error('Failed to search purchase orders');
    } finally {
      setPoLoading(false);
    }
  }, [formData.vendor_id]);
  
  // Select vendor from dropdown
  const selectVendor = (vendor) => {
    setFormData(prev => ({
      ...prev,
      vendor_id: vendor.number || vendor.id,
      vendor_name_resolved: vendor.displayName
    }));
    setVendorSearch(vendor.displayName);
    setShowVendorDropdown(false);
  };
  
  // Select PO from dropdown
  const selectPO = (po) => {
    setFormData(prev => ({
      ...prev,
      po_number: po.number
    }));
    setShowPoDropdown(false);
  };
  
  // Add line item
  const addLineItem = () => {
    setFormData(prev => ({
      ...prev,
      line_items: [...prev.line_items, { description: '', quantity: 1, unit_price: 0, line_total: 0 }]
    }));
  };
  
  // Update line item
  const updateLineItem = (index, field, value) => {
    setFormData(prev => {
      const items = [...prev.line_items];
      items[index] = { ...items[index], [field]: value };
      // Calculate line total
      if (field === 'quantity' || field === 'unit_price') {
        items[index].line_total = (parseFloat(items[index].quantity) || 0) * (parseFloat(items[index].unit_price) || 0);
      }
      return { ...prev, line_items: items };
    });
  };
  
  // Remove line item
  const removeLineItem = (index) => {
    setFormData(prev => ({
      ...prev,
      line_items: prev.line_items.filter((_, i) => i !== index)
    }));
  };
  
  // Save changes
  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await saveAPReview(document.id, {
        ...formData,
        total_amount: parseFloat(formData.total_amount) || null,
        tax_amount: parseFloat(formData.tax_amount) || null
      });
      toast.success('Changes saved');
      if (onUpdate) onUpdate(res.data.document);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };
  
  // Mark ready for post
  const handleMarkReady = async () => {
    setMarkingReady(true);
    try {
      // Save first
      await saveAPReview(document.id, {
        ...formData,
        total_amount: parseFloat(formData.total_amount) || null,
        tax_amount: parseFloat(formData.tax_amount) || null
      });
      // Then mark ready
      const res = await markReadyForPost(document.id);
      toast.success('Document marked ready for posting');
      if (onUpdate) onUpdate(res.data.document);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to mark ready');
    } finally {
      setMarkingReady(false);
    }
  };
  
  // Post to BC
  const handlePostToBC = async () => {
    setPosting(true);
    try {
      const res = await postToBC(document.id);
      if (res.data.success) {
        toast.success(`Posted to BC: ${res.data.bc_document_number || res.data.bc_document_id}`);
        if (onUpdate) {
          // Refresh document
          const updatedDoc = {
            ...document,
            bc_document_id: res.data.bc_document_id,
            bc_document_number: res.data.bc_document_number,
            bc_posting_status: res.data.bc_posting_status,
            review_status: 'posted',
            status: 'Posted'
          };
          onUpdate(updatedDoc);
        }
      } else {
        toast.error(res.data.error || 'Failed to post to BC');
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to post to BC');
    } finally {
      setPosting(false);
    }
  };
  
  const reviewStatus = document?.review_status || '';
  const bcPostingStatus = document?.bc_posting_status || '';
  const isPosted = bcPostingStatus === 'posted';
  const isReadyForPost = reviewStatus === 'ready_for_post';
  
  return (
    <Card className="border border-border" data-testid="ap-review-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <FileText className="w-4 h-4" />
            AP Invoice Review
          </CardTitle>
          <div className="flex items-center gap-2">
            {isPosted && (
              <Badge variant="secondary" className="bg-emerald-100 text-emerald-800">
                <CheckCircle2 className="w-3 h-3 mr-1" />
                Posted
              </Badge>
            )}
            {bcPostingStatus === 'failed' && (
              <Badge variant="destructive">
                <AlertCircle className="w-3 h-3 mr-1" />
                Post Failed
              </Badge>
            )}
            {isReadyForPost && !isPosted && (
              <Badge variant="secondary" className="bg-blue-100 text-blue-800">
                Ready to Post
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Vendor Selection */}
        <div className="space-y-2">
          <Label className="text-xs flex items-center gap-1">
            <Building2 className="w-3 h-3" /> Vendor
          </Label>
          <div className="relative">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input 
                  value={vendorSearch}
                  onChange={(e) => setVendorSearch(e.target.value)}
                  onFocus={() => vendorResults.length > 0 && setShowVendorDropdown(true)}
                  placeholder="Search vendor..."
                  className="h-8 text-xs pr-8"
                  disabled={isPosted}
                  data-testid="vendor-search-input"
                />
                {vendorLoading && (
                  <Loader2 className="w-3 h-3 absolute right-2 top-2.5 animate-spin text-muted-foreground" />
                )}
              </div>
              <Button 
                variant="outline" 
                size="sm" 
                className="h-8"
                onClick={() => handleVendorSearch(vendorSearch)}
                disabled={isPosted}
              >
                <Search className="w-3 h-3" />
              </Button>
            </div>
            {/* Vendor dropdown */}
            {showVendorDropdown && vendorResults.length > 0 && (
              <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg max-h-48 overflow-auto">
                {vendorResults.map((v) => (
                  <button
                    key={v.id || v.number}
                    className="w-full px-3 py-2 text-left text-xs hover:bg-muted flex justify-between items-center"
                    onClick={() => selectVendor(v)}
                  >
                    <span className="font-medium">{v.displayName}</span>
                    <span className="text-muted-foreground font-mono">{v.number}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          {formData.vendor_id && (
            <p className="text-[10px] text-muted-foreground font-mono">
              Vendor ID: {formData.vendor_id}
            </p>
          )}
        </div>
        
        {/* Invoice Details Grid */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-xs flex items-center gap-1">
              <Hash className="w-3 h-3" /> Invoice #
            </Label>
            <Input 
              value={formData.invoice_number}
              onChange={(e) => setFormData(prev => ({ ...prev, invoice_number: e.target.value }))}
              className="h-8 text-xs"
              disabled={isPosted}
              data-testid="invoice-number-input"
            />
          </div>
          
          <div className="space-y-1">
            <Label className="text-xs flex items-center gap-1">
              <Calendar className="w-3 h-3" /> Invoice Date
            </Label>
            <Input 
              type="date"
              value={formData.invoice_date}
              onChange={(e) => setFormData(prev => ({ ...prev, invoice_date: e.target.value }))}
              className="h-8 text-xs"
              disabled={isPosted}
              data-testid="invoice-date-input"
            />
          </div>
          
          <div className="space-y-1">
            <Label className="text-xs flex items-center gap-1">
              <Calendar className="w-3 h-3" /> Due Date
            </Label>
            <Input 
              type="date"
              value={formData.due_date}
              onChange={(e) => setFormData(prev => ({ ...prev, due_date: e.target.value }))}
              className="h-8 text-xs"
              disabled={isPosted}
              data-testid="due-date-input"
            />
          </div>
          
          <div className="space-y-1">
            <Label className="text-xs">Currency</Label>
            <Select 
              value={formData.currency} 
              onValueChange={(val) => setFormData(prev => ({ ...prev, currency: val }))}
              disabled={isPosted}
            >
              <SelectTrigger className="h-8 text-xs" data-testid="currency-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          
          <div className="space-y-1">
            <Label className="text-xs flex items-center gap-1">
              <DollarSign className="w-3 h-3" /> Total Amount
            </Label>
            <Input 
              type="number"
              step="0.01"
              value={formData.total_amount}
              onChange={(e) => setFormData(prev => ({ ...prev, total_amount: e.target.value }))}
              className="h-8 text-xs"
              disabled={isPosted}
              data-testid="total-amount-input"
            />
          </div>
          
          <div className="space-y-1">
            <Label className="text-xs">Tax Amount</Label>
            <Input 
              type="number"
              step="0.01"
              value={formData.tax_amount}
              onChange={(e) => setFormData(prev => ({ ...prev, tax_amount: e.target.value }))}
              className="h-8 text-xs"
              disabled={isPosted}
              data-testid="tax-amount-input"
            />
          </div>
        </div>
        
        {/* PO Selection */}
        <div className="space-y-2">
          <Label className="text-xs flex items-center gap-1">
            <Package className="w-3 h-3" /> PO Number
          </Label>
          <div className="flex gap-2">
            <Input 
              value={formData.po_number}
              onChange={(e) => setFormData(prev => ({ ...prev, po_number: e.target.value }))}
              placeholder="Enter or search PO..."
              className="h-8 text-xs flex-1"
              disabled={isPosted}
              data-testid="po-number-input"
            />
            <Button 
              variant="outline" 
              size="sm" 
              className="h-8"
              onClick={handlePoSearch}
              disabled={!formData.vendor_id || isPosted || poLoading}
            >
              {poLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
            </Button>
          </div>
          {/* PO dropdown */}
          {showPoDropdown && poResults.length > 0 && (
            <div className="border rounded-md shadow-sm max-h-32 overflow-auto">
              {poResults.map((po) => (
                <button
                  key={po.id || po.number}
                  className="w-full px-3 py-2 text-left text-xs hover:bg-muted flex justify-between items-center border-b last:border-0"
                  onClick={() => selectPO(po)}
                >
                  <span className="font-mono font-medium">{po.number}</span>
                  <span className="text-muted-foreground">${po.totalAmountIncludingVat?.toLocaleString()}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        
        {/* Line Items */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs">Line Items</Label>
            {!isPosted && (
              <Button 
                variant="ghost" 
                size="sm" 
                className="h-6 text-xs"
                onClick={addLineItem}
              >
                <Plus className="w-3 h-3 mr-1" /> Add Line
              </Button>
            )}
          </div>
          
          {formData.line_items.length > 0 ? (
            <div className="space-y-2">
              {formData.line_items.map((line, idx) => (
                <div key={idx} className="flex gap-2 items-start bg-muted/50 rounded p-2">
                  <div className="flex-1 space-y-1">
                    <Input 
                      value={line.description}
                      onChange={(e) => updateLineItem(idx, 'description', e.target.value)}
                      placeholder="Description"
                      className="h-7 text-xs"
                      disabled={isPosted}
                    />
                    <div className="flex gap-2">
                      <Input 
                        type="number"
                        value={line.quantity}
                        onChange={(e) => updateLineItem(idx, 'quantity', e.target.value)}
                        placeholder="Qty"
                        className="h-6 text-xs w-16"
                        disabled={isPosted}
                      />
                      <Input 
                        type="number"
                        step="0.01"
                        value={line.unit_price}
                        onChange={(e) => updateLineItem(idx, 'unit_price', e.target.value)}
                        placeholder="Unit $"
                        className="h-6 text-xs w-20"
                        disabled={isPosted}
                      />
                      <span className="text-xs text-muted-foreground self-center">
                        = ${(line.line_total || 0).toFixed(2)}
                      </span>
                    </div>
                  </div>
                  {!isPosted && (
                    <Button 
                      variant="ghost" 
                      size="icon" 
                      className="h-6 w-6 text-muted-foreground hover:text-destructive"
                      onClick={() => removeLineItem(idx)}
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-2">
              No line items. Click "Add Line" to add.
            </p>
          )}
        </div>
        
        {/* BC Posting Error */}
        {document?.bc_posting_error && (
          <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-2.5">
            <p className="text-xs font-medium text-red-700 dark:text-red-300">Posting Error</p>
            <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">{document.bc_posting_error}</p>
          </div>
        )}
        
        {/* BC Document Info (if posted) */}
        {isPosted && document?.bc_document_id && (
          <div className="bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 rounded-md p-2.5 space-y-2">
            <div>
              <p className="text-xs font-medium text-emerald-700 dark:text-emerald-300">Posted to Business Central</p>
              <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5 font-mono">
                BC Document: {document.bc_document_number || document.bc_document_id}
              </p>
            </div>
            
            {/* SharePoint URL */}
            {document.sharepoint_share_link_url && (
              <div className="pt-1.5 border-t border-emerald-200 dark:border-emerald-700">
                <p className="text-[10px] font-medium text-emerald-600 dark:text-emerald-400">SharePoint Document</p>
                <a 
                  href={document.sharepoint_share_link_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-[10px] text-blue-600 hover:underline break-all"
                  data-testid="sharepoint-link"
                >
                  {document.sharepoint_share_link_url.length > 60 
                    ? document.sharepoint_share_link_url.substring(0, 60) + '...' 
                    : document.sharepoint_share_link_url}
                </a>
              </div>
            )}
            
            {/* BC Link Writeback Status */}
            <div className="pt-1.5 border-t border-emerald-200 dark:border-emerald-700">
              <p className="text-[10px] font-medium text-emerald-600 dark:text-emerald-400">BC Link Writeback</p>
              {document.bc_link_writeback_status === 'success' && (
                <p className="text-[10px] text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" /> Link written to BC invoice
                </p>
              )}
              {document.bc_link_writeback_status === 'failed' && (
                <p className="text-[10px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> 
                  Writeback failed: {document.bc_link_writeback_error || 'Unknown error'}
                </p>
              )}
              {document.bc_link_writeback_status === 'skipped' && (
                <p className="text-[10px] text-muted-foreground flex items-center gap-1">
                  Skipped: {document.bc_link_writeback_error || 'No SharePoint URL'}
                </p>
              )}
              {!document.bc_link_writeback_status && (
                <p className="text-[10px] text-muted-foreground">Not attempted</p>
              )}
            </div>
          </div>
        )}
        
        {/* Action Buttons */}
        <div className="flex gap-2 pt-2 border-t">
          <Button 
            variant="outline" 
            size="sm" 
            className="flex-1 h-8"
            onClick={handleSave}
            disabled={saving || isPosted}
            data-testid="save-ap-review-btn"
          >
            {saving ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
            Save Changes
          </Button>
          
          {!isReadyForPost && !isPosted && (
            <Button 
              variant="secondary" 
              size="sm" 
              className="flex-1 h-8"
              onClick={handleMarkReady}
              disabled={markingReady || !formData.vendor_id || !formData.invoice_number}
              data-testid="mark-ready-btn"
            >
              {markingReady ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <CheckCircle2 className="w-3 h-3 mr-1" />}
              Mark Ready
            </Button>
          )}
          
          {(isReadyForPost || bcPostingStatus === 'failed') && !isPosted && (
            <Button 
              size="sm" 
              className="flex-1 h-8 bg-emerald-600 hover:bg-emerald-700"
              onClick={handlePostToBC}
              disabled={posting}
              data-testid="post-to-bc-btn"
            >
              {posting ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Send className="w-3 h-3 mr-1" />}
              Post to BC
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default APReviewPanel;
