import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import { 
  Search, Filter, RefreshCw, FileText, Clock, CheckCircle2, 
  AlertCircle, Archive, ChevronRight, Inbox, FileCheck, Play
} from "lucide-react";
import api, { bulkResubmitDocuments } from "@/lib/api";

// Document types and their display names
const DOC_TYPES = {
  ALL: { label: "All Types", color: "default" },
  AP_INVOICE: { label: "AP Invoice", color: "blue" },
  SALES_ORDER: { label: "Sales Order", color: "green" },
  PURCHASE_ORDER: { label: "Purchase Order", color: "purple" },
  SALES_CREDIT_MEMO: { label: "Sales Credit", color: "orange" },
  PURCHASE_CREDIT_MEMO: { label: "Purchase Credit", color: "orange" },
  STATEMENT: { label: "Statement", color: "gray" },
  OTHER: { label: "Other", color: "default" }
};

// Workflow statuses and their display
const STATUSES = {
  ALL: { label: "All Status", color: "default" },
  received: { label: "Received", color: "gray" },
  classified: { label: "Classified", color: "blue" },
  extracted: { label: "Extracted", color: "blue" },
  pending_review: { label: "Pending Review", color: "yellow" },
  vendor_pending: { label: "Vendor Pending", color: "yellow" },
  bc_validation_pending: { label: "BC Validation", color: "yellow" },
  ready_for_approval: { label: "Ready for Approval", color: "green" },
  approved: { label: "Approved", color: "green" },
  rejected: { label: "Rejected", color: "red" },
  exported: { label: "Exported", color: "green" },
  archived: { label: "Archived", color: "gray" }
};

const getStatusBadge = (status) => {
  const config = STATUSES[status] || { label: status, color: "default" };
  const colorClass = {
    gray: "bg-gray-500/20 text-gray-400",
    blue: "bg-blue-500/20 text-blue-400",
    yellow: "bg-yellow-500/20 text-yellow-400",
    green: "bg-green-500/20 text-green-400",
    red: "bg-red-500/20 text-red-400",
    default: "bg-gray-500/20 text-gray-400"
  }[config.color] || "bg-gray-500/20 text-gray-400";
  
  return <Badge className={colorClass}>{config.label}</Badge>;
};

const getTypeBadge = (docType) => {
  const config = DOC_TYPES[docType] || { label: docType, color: "default" };
  const colorClass = {
    blue: "bg-blue-500/20 text-blue-400",
    green: "bg-green-500/20 text-green-400",
    purple: "bg-purple-500/20 text-purple-400",
    orange: "bg-orange-500/20 text-orange-400",
    gray: "bg-gray-500/20 text-gray-400",
    default: "bg-gray-500/20 text-gray-400"
  }[config.color] || "bg-gray-500/20 text-gray-400";
  
  return <Badge className={colorClass}>{config.label}</Badge>;
};

export default function UnifiedQueuePage() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ total: 0, by_status: {}, by_type: {} });
  
  // Filters
  const [docTypeFilter, setDocTypeFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState("pending");

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      // Build query params
      const params = new URLSearchParams();
      if (docTypeFilter !== "ALL") params.append("doc_type", docTypeFilter);
      if (statusFilter !== "ALL") params.append("status", statusFilter);
      if (searchQuery) params.append("search", searchQuery);
      
      // For pending tab, filter out completed/archived
      if (activeTab === "pending") {
        params.append("exclude_status", "archived,exported,completed");
      } else if (activeTab === "completed") {
        params.append("status", "exported,archived,completed");
      }
      
      const response = await api.get(`/documents?${params.toString()}`);
      setDocuments(response.data.documents || []);
    } catch (err) {
      console.error("Failed to fetch documents:", err);
      toast.error("Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [docTypeFilter, statusFilter, searchQuery, activeTab]);

  const fetchStats = useCallback(async () => {
    try {
      const response = await api.get("/dashboard/stats");
      setStats({
        total: response.data.total_documents || 0,
        by_status: response.data.by_status || {},
        by_type: response.data.by_type || {}
      });
    } catch (err) {
      console.error("Failed to fetch stats:", err);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
    fetchStats();
  }, [fetchDocuments, fetchStats]);

  const handleRefresh = () => {
    fetchDocuments();
    fetchStats();
    toast.success("Queue refreshed");
  };

  const pendingCount = Object.entries(stats.by_status)
    .filter(([status]) => !["archived", "exported", "completed", "approved"].includes(status))
    .reduce((sum, [, count]) => sum + count, 0);

  const completedCount = (stats.by_status.archived || 0) + 
                         (stats.by_status.exported || 0) + 
                         (stats.by_status.completed || 0);

  return (
    <div className="space-y-6" data-testid="unified-queue-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Document Queue</h1>
          <p className="text-muted-foreground">
            Manage all documents across workflows
          </p>
        </div>
        <Button onClick={handleRefresh} variant="outline" size="sm">
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-muted-foreground" />
              <div>
                <div className="text-2xl font-bold">{stats.total}</div>
                <div className="text-xs text-muted-foreground">Total Documents</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-yellow-500" />
              <div>
                <div className="text-2xl font-bold">{pendingCount}</div>
                <div className="text-xs text-muted-foreground">Pending Review</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-green-500" />
              <div>
                <div className="text-2xl font-bold">{completedCount}</div>
                <div className="text-xs text-muted-foreground">Completed</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Inbox className="h-5 w-5 text-blue-500" />
              <div>
                <div className="text-2xl font-bold">{Object.keys(stats.by_type).length}</div>
                <div className="text-xs text-muted-foreground">Document Types</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-4 items-center">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Filters:</span>
            </div>
            
            <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
              <SelectTrigger className="w-[180px]" data-testid="filter-doc-type">
                <SelectValue placeholder="Document Type" />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(DOC_TYPES).map(([key, { label }]) => (
                  <SelectItem key={key} value={key}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[180px]" data-testid="filter-status">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(STATUSES).map(([key, { label }]) => (
                  <SelectItem key={key} value={key}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="flex-1 max-w-sm">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search documents..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10"
                  data-testid="search-input"
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabs and Table */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="pending" data-testid="tab-pending">
            <Clock className="h-4 w-4 mr-2" />
            Pending ({pendingCount})
          </TabsTrigger>
          <TabsTrigger value="completed" data-testid="tab-completed">
            <FileCheck className="h-4 w-4 mr-2" />
            Completed ({completedCount})
          </TabsTrigger>
          <TabsTrigger value="all" data-testid="tab-all">
            All ({stats.total})
          </TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} className="mt-4">
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="p-8 text-center text-muted-foreground">
                  Loading documents...
                </div>
              ) : documents.length === 0 ? (
                <div className="p-8 text-center text-muted-foreground">
                  No documents found
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Document</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Source</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead className="w-10"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {documents.map((doc) => (
                      <TableRow 
                        key={doc.id} 
                        className="cursor-pointer hover:bg-muted/50"
                        onClick={() => navigate(`/documents/${doc.id}`)}
                        data-testid={`doc-row-${doc.id}`}
                      >
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <FileText className="h-4 w-4 text-muted-foreground" />
                            <div>
                              <div className="font-medium truncate max-w-[200px]">
                                {doc.file_name || "Unnamed"}
                              </div>
                              {doc.extracted_fields?.invoice_number && (
                                <div className="text-xs text-muted-foreground">
                                  #{doc.extracted_fields.invoice_number}
                                </div>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>{getTypeBadge(doc.doc_type)}</TableCell>
                        <TableCell>{getStatusBadge(doc.workflow_status || doc.status)}</TableCell>
                        <TableCell>
                          <span className="text-sm text-muted-foreground">
                            {doc.source || "unknown"}
                          </span>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm text-muted-foreground">
                            {doc.created_utc ? new Date(doc.created_utc).toLocaleDateString() : "-"}
                          </span>
                        </TableCell>
                        <TableCell>
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
