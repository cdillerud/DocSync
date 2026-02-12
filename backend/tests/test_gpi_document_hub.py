"""
GPI Document Hub Backend API Tests
Tests for document upload, BC integration, and workflow management
"""
import pytest
import requests
import os
import time
import io

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestHealthAndAuth:
    """Basic health and authentication tests"""
    
    def test_api_accessible(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        data = response.json()
        assert "demo_mode" in data
        assert "connections" in data
        print(f"API accessible. Demo mode: {data['demo_mode']}")
    
    def test_auth_login_success(self):
        """Test login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["username"] == "admin"
        print(f"Login successful. User: {data['user']['display_name']}")
    
    def test_auth_login_invalid(self):
        """Test login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "wrong",
            "password": "wrong"
        })
        assert response.status_code == 401
        print("Invalid login correctly rejected")
    
    def test_auth_me(self):
        """Test /auth/me endpoint"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert "username" in data
        assert "role" in data
        print(f"Auth me: {data['username']}, role: {data['role']}")


class TestBCConnection:
    """Business Central connection and integration tests"""
    
    def test_bc_connection_test(self):
        """Test BC connection via test-connection endpoint"""
        response = requests.post(f"{BASE_URL}/api/settings/test-connection?service=bc")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "bc"
        assert data["status"] in ["ok", "demo", "error"]
        print(f"BC connection test: {data['status']} - {data['detail']}")
        # In live mode, we expect 'ok' status
        if data["status"] == "error":
            pytest.skip(f"BC connection error: {data['detail']}")
    
    def test_graph_connection_test(self):
        """Test SharePoint/Graph connection"""
        response = requests.post(f"{BASE_URL}/api/settings/test-connection?service=graph")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "graph"
        assert data["status"] in ["ok", "demo", "error"]
        print(f"Graph connection test: {data['status']} - {data['detail']}")
    
    def test_bc_sales_orders_list(self):
        """Test GET /api/bc/sales-orders - list sales orders"""
        response = requests.get(f"{BASE_URL}/api/bc/sales-orders")
        assert response.status_code == 200
        data = response.json()
        assert "orders" in data
        print(f"BC Sales Orders: Found {len(data['orders'])} orders")
        if data.get("warning"):
            print(f"Warning: {data['warning']}")
        return data["orders"]
    
    def test_bc_sales_orders_search(self):
        """Test GET /api/bc/sales-orders with search parameter"""
        # First get all orders to find a valid order number
        response = requests.get(f"{BASE_URL}/api/bc/sales-orders")
        assert response.status_code == 200
        orders = response.json().get("orders", [])
        
        if orders:
            # Search for the first order
            order_no = orders[0].get("number", "")
            search_response = requests.get(f"{BASE_URL}/api/bc/sales-orders?search={order_no}")
            assert search_response.status_code == 200
            search_data = search_response.json()
            assert "orders" in search_data
            print(f"Search for '{order_no}': Found {len(search_data['orders'])} orders")
        else:
            print("No orders available for search test")
    
    def test_bc_companies_list(self):
        """Test GET /api/bc/companies"""
        response = requests.get(f"{BASE_URL}/api/bc/companies")
        assert response.status_code == 200
        data = response.json()
        assert "companies" in data
        print(f"BC Companies: Found {len(data['companies'])} companies")
        for company in data["companies"][:3]:
            print(f"  - {company.get('displayName', company.get('name', 'Unknown'))}")


class TestDashboard:
    """Dashboard statistics tests"""
    
    def test_dashboard_stats(self):
        """Test GET /api/dashboard/stats"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        
        # Verify required fields
        assert "total_documents" in data
        assert "by_status" in data
        assert "by_type" in data
        assert "recent_workflows" in data
        assert "failed_workflows" in data
        assert "demo_mode" in data
        
        print(f"Dashboard stats:")
        print(f"  Total documents: {data['total_documents']}")
        print(f"  By status: {data['by_status']}")
        print(f"  By type: {data['by_type']}")
        print(f"  Recent workflows: {len(data['recent_workflows'])}")
        print(f"  Failed workflows: {len(data['failed_workflows'])}")
        print(f"  Demo mode: {data['demo_mode']}")


class TestDocuments:
    """Document CRUD and workflow tests"""
    
    def test_documents_list(self):
        """Test GET /api/documents - list documents"""
        response = requests.get(f"{BASE_URL}/api/documents")
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "total" in data
        print(f"Documents list: {data['total']} total documents")
        return data["documents"]
    
    def test_documents_list_with_filters(self):
        """Test GET /api/documents with status and type filters"""
        # Test status filter
        response = requests.get(f"{BASE_URL}/api/documents?status=LinkedToBC")
        assert response.status_code == 200
        data = response.json()
        print(f"Documents with status=LinkedToBC: {data['total']}")
        
        # Test document_type filter
        response = requests.get(f"{BASE_URL}/api/documents?document_type=SalesOrder")
        assert response.status_code == 200
        data = response.json()
        print(f"Documents with type=SalesOrder: {data['total']}")
        
        # Test search filter
        response = requests.get(f"{BASE_URL}/api/documents?search=test")
        assert response.status_code == 200
        data = response.json()
        print(f"Documents matching 'test': {data['total']}")
    
    def test_document_get_existing(self):
        """Test GET /api/documents/{doc_id} for existing document"""
        # First get list of documents
        list_response = requests.get(f"{BASE_URL}/api/documents")
        assert list_response.status_code == 200
        documents = list_response.json().get("documents", [])
        
        if documents:
            doc_id = documents[0]["id"]
            response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
            assert response.status_code == 200
            data = response.json()
            assert "document" in data
            assert "workflows" in data
            print(f"Document detail: {data['document']['file_name']}")
            print(f"  Status: {data['document']['status']}")
            print(f"  Workflows: {len(data['workflows'])}")
        else:
            print("No documents available for detail test")
    
    def test_document_get_not_found(self):
        """Test GET /api/documents/{doc_id} for non-existent document"""
        response = requests.get(f"{BASE_URL}/api/documents/non-existent-id-12345")
        assert response.status_code == 404
        print("Non-existent document correctly returns 404")


class TestDocumentUpload:
    """Document upload workflow tests"""
    
    @pytest.fixture
    def test_pdf_content(self):
        """Create a minimal valid PDF for testing"""
        # Minimal PDF content
        pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF"""
        return pdf_content
    
    def test_document_upload_without_bc(self, test_pdf_content):
        """Test document upload without BC linking"""
        files = {
            'file': ('TEST_upload_no_bc.pdf', io.BytesIO(test_pdf_content), 'application/pdf')
        }
        data = {
            'document_type': 'Other',
            'source': 'test_upload'
        }
        
        response = requests.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)
        assert response.status_code == 200
        result = response.json()
        
        assert "document" in result
        assert "workflow_id" in result
        
        doc = result["document"]
        assert doc["file_name"] == "TEST_upload_no_bc.pdf"
        assert doc["status"] in ["Classified", "LinkedToBC", "Exception"]
        
        print(f"Upload without BC:")
        print(f"  Document ID: {doc['id']}")
        print(f"  Status: {doc['status']}")
        print(f"  SharePoint URL: {doc.get('sharepoint_web_url', 'N/A')}")
        
        return doc["id"]
    
    def test_document_upload_with_bc_order(self, test_pdf_content):
        """Test document upload with BC Sales Order linking"""
        # First get a valid sales order
        orders_response = requests.get(f"{BASE_URL}/api/bc/sales-orders")
        orders = orders_response.json().get("orders", [])
        
        if not orders:
            # Check if there's an existing document with a BC order
            docs_response = requests.get(f"{BASE_URL}/api/documents")
            docs = docs_response.json().get("documents", [])
            bc_doc = next((d for d in docs if d.get("bc_document_no")), None)
            if bc_doc:
                order_no = bc_doc["bc_document_no"]
                order_id = bc_doc.get("bc_record_id")
            else:
                pytest.skip("No BC sales orders available for testing")
                return
        else:
            order_no = orders[0]["number"]
            order_id = orders[0]["id"]
        
        files = {
            'file': ('TEST_upload_with_bc.pdf', io.BytesIO(test_pdf_content), 'application/pdf')
        }
        data = {
            'document_type': 'SalesOrder',
            'bc_document_no': order_no,
            'bc_record_id': order_id,
            'source': 'test_upload'
        }
        
        response = requests.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)
        assert response.status_code == 200
        result = response.json()
        
        assert "document" in result
        assert "workflow_id" in result
        
        doc = result["document"]
        print(f"Upload with BC order {order_no}:")
        print(f"  Document ID: {doc['id']}")
        print(f"  Status: {doc['status']}")
        print(f"  BC Document No: {doc.get('bc_document_no')}")
        print(f"  SharePoint URL: {doc.get('sharepoint_web_url', 'N/A')}")
        print(f"  Last Error: {doc.get('last_error', 'None')}")
        
        return doc["id"]


class TestDocumentResubmit:
    """Document resubmit workflow tests"""
    
    def test_resubmit_existing_document(self):
        """Test POST /api/documents/{doc_id}/resubmit"""
        # Get an existing document
        list_response = requests.get(f"{BASE_URL}/api/documents")
        documents = list_response.json().get("documents", [])
        
        if not documents:
            pytest.skip("No documents available for resubmit test")
            return
        
        doc_id = documents[0]["id"]
        original_status = documents[0]["status"]
        
        response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/resubmit")
        assert response.status_code == 200
        result = response.json()
        
        assert "document" in result
        assert "workflow_id" in result
        
        doc = result["document"]
        print(f"Resubmit document {doc_id}:")
        print(f"  Original status: {original_status}")
        print(f"  New status: {doc['status']}")
        print(f"  Workflow ID: {result['workflow_id']}")
    
    def test_resubmit_not_found(self):
        """Test resubmit for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/documents/non-existent-id-12345/resubmit")
        assert response.status_code == 404
        print("Resubmit non-existent document correctly returns 404")


class TestDocumentLink:
    """Document link to BC tests"""
    
    def test_link_document_to_bc(self):
        """Test POST /api/documents/{doc_id}/link"""
        # Get a document that has SharePoint link but might need BC linking
        list_response = requests.get(f"{BASE_URL}/api/documents")
        documents = list_response.json().get("documents", [])
        
        # Find a document with SharePoint link and BC reference
        eligible_doc = None
        for doc in documents:
            if doc.get("sharepoint_share_link_url") and (doc.get("bc_record_id") or doc.get("bc_document_no")):
                eligible_doc = doc
                break
        
        if not eligible_doc:
            pytest.skip("No eligible document for link test (needs SharePoint link and BC reference)")
            return
        
        doc_id = eligible_doc["id"]
        response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/link")
        assert response.status_code == 200
        result = response.json()
        
        assert "document" in result
        assert "workflow_id" in result
        
        doc = result["document"]
        print(f"Link document {doc_id} to BC:")
        print(f"  Status: {doc['status']}")
        print(f"  BC Document No: {doc.get('bc_document_no')}")
        print(f"  Last Error: {doc.get('last_error', 'None')}")
    
    def test_link_document_not_found(self):
        """Test link for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/documents/non-existent-id-12345/link")
        assert response.status_code == 404
        print("Link non-existent document correctly returns 404")
    
    def test_link_document_no_sharepoint(self):
        """Test link for document without SharePoint link"""
        # This would require creating a document without SharePoint link
        # which is not typical in normal flow, so we skip this test
        pytest.skip("Cannot test - documents always get SharePoint link on upload")


class TestSettings:
    """Settings and configuration tests"""
    
    def test_settings_status(self):
        """Test GET /api/settings/status"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        data = response.json()
        
        assert "demo_mode" in data
        assert "connections" in data
        
        connections = data["connections"]
        assert "mongodb" in connections
        assert "sharepoint" in connections
        assert "business_central" in connections
        assert "entra_id" in connections
        
        print(f"Settings status:")
        print(f"  Demo mode: {data['demo_mode']}")
        for service, status in connections.items():
            print(f"  {service}: {status.get('status', 'unknown')}")
    
    def test_settings_config(self):
        """Test GET /api/settings/config"""
        response = requests.get(f"{BASE_URL}/api/settings/config")
        assert response.status_code == 200
        data = response.json()
        
        assert "config" in data
        config = data["config"]
        
        # Verify secrets are masked
        if config.get("BC_CLIENT_SECRET"):
            assert "****" in config["BC_CLIENT_SECRET"] or len(config["BC_CLIENT_SECRET"]) < 10
        if config.get("GRAPH_CLIENT_SECRET"):
            assert "****" in config["GRAPH_CLIENT_SECRET"] or len(config["GRAPH_CLIENT_SECRET"]) < 10
        
        print(f"Settings config retrieved (secrets masked)")


class TestWorkflows:
    """Workflow management tests"""
    
    def test_workflows_list(self):
        """Test GET /api/workflows"""
        response = requests.get(f"{BASE_URL}/api/workflows")
        assert response.status_code == 200
        data = response.json()
        
        assert "workflows" in data
        assert "total" in data
        
        print(f"Workflows: {data['total']} total")
        for wf in data["workflows"][:3]:
            print(f"  - {wf['id'][:8]}... : {wf['workflow_name']} - {wf['status']}")
    
    def test_workflows_list_with_filter(self):
        """Test GET /api/workflows with status filter"""
        response = requests.get(f"{BASE_URL}/api/workflows?status=Completed")
        assert response.status_code == 200
        data = response.json()
        print(f"Completed workflows: {data['total']}")
    
    def test_workflow_get_existing(self):
        """Test GET /api/workflows/{wf_id}"""
        # Get list of workflows
        list_response = requests.get(f"{BASE_URL}/api/workflows")
        workflows = list_response.json().get("workflows", [])
        
        if workflows:
            wf_id = workflows[0]["id"]
            response = requests.get(f"{BASE_URL}/api/workflows/{wf_id}")
            assert response.status_code == 200
            wf = response.json()
            
            assert "id" in wf
            assert "steps" in wf
            assert "status" in wf
            
            print(f"Workflow detail: {wf['id']}")
            print(f"  Name: {wf['workflow_name']}")
            print(f"  Status: {wf['status']}")
            print(f"  Steps: {len(wf['steps'])}")
        else:
            print("No workflows available for detail test")
    
    def test_workflow_get_not_found(self):
        """Test GET /api/workflows/{wf_id} for non-existent workflow"""
        response = requests.get(f"{BASE_URL}/api/workflows/non-existent-id-12345")
        assert response.status_code == 404
        print("Non-existent workflow correctly returns 404")


class TestDocumentDelete:
    """Document deletion tests - run last to clean up test data"""
    
    def test_delete_test_documents(self):
        """Delete TEST_ prefixed documents created during testing"""
        list_response = requests.get(f"{BASE_URL}/api/documents?search=TEST_")
        documents = list_response.json().get("documents", [])
        
        deleted_count = 0
        for doc in documents:
            if doc["file_name"].startswith("TEST_"):
                response = requests.delete(f"{BASE_URL}/api/documents/{doc['id']}")
                if response.status_code == 200:
                    deleted_count += 1
                    print(f"Deleted test document: {doc['file_name']}")
        
        print(f"Cleanup: Deleted {deleted_count} test documents")
    
    def test_delete_not_found(self):
        """Test DELETE /api/documents/{doc_id} for non-existent document"""
        response = requests.delete(f"{BASE_URL}/api/documents/non-existent-id-12345")
        assert response.status_code == 404
        print("Delete non-existent document correctly returns 404")


# Cleanup fixture to run after all tests
@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data():
    """Cleanup TEST_ prefixed data after all tests complete"""
    yield
    # Teardown: Delete all test-created documents
    try:
        response = requests.get(f"{BASE_URL}/api/documents?search=TEST_")
        if response.status_code == 200:
            documents = response.json().get("documents", [])
            for doc in documents:
                if doc["file_name"].startswith("TEST_"):
                    requests.delete(f"{BASE_URL}/api/documents/{doc['id']}")
    except Exception as e:
        print(f"Cleanup error: {e}")
