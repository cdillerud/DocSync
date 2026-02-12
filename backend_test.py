#!/usr/bin/env python3
"""
GPI Document Hub - Backend API Test Suite
Tests all backend API endpoints using the production URL
"""
import requests
import sys
import json
from datetime import datetime

class GPIDocumentHubTester:
    def __init__(self, base_url="https://docsync-central-1.preview.emergentagent.com"):
        self.base_url = base_url
        self.api = f"{base_url}/api"
        self.token = None
        self.headers = {}
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {name}")
        if details:
            print(f"    {details}")
        self.test_results.append({
            "name": name,
            "success": success,
            "details": details
        })

    def test_login(self):
        """Test login functionality"""
        print("\n🔐 Testing Authentication...")
        try:
            resp = requests.post(f"{self.api}/auth/login", 
                               json={"username": "admin", "password": "admin"},
                               timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                self.token = data["token"]
                self.headers = {"Authorization": f"Bearer {self.token}"}
                user = data["user"]
                self.log_test("Login API", True, 
                            f"Token received, User: {user['display_name']} ({user['role']})")
                return True
            else:
                self.log_test("Login API", False, f"Status {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            self.log_test("Login API", False, f"Error: {str(e)}")
            return False

    def test_auth_me(self):
        """Test auth/me endpoint"""
        print("\n👤 Testing User Info...")
        try:
            resp = requests.get(f"{self.api}/auth/me", headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                user = resp.json()
                self.log_test("User Info API", True, 
                            f"User: {user['username']} - {user['display_name']}")
                return True
            else:
                self.log_test("User Info API", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.log_test("User Info API", False, f"Error: {str(e)}")
            return False

    def test_dashboard_stats(self):
        """Test dashboard statistics"""
        print("\n📊 Testing Dashboard...")
        try:
            resp = requests.get(f"{self.api}/dashboard/stats", headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                stats = resp.json()
                self.log_test("Dashboard Stats", True, 
                            f"Total docs: {stats['total_documents']}, Demo mode: {stats['demo_mode']}")
                return stats
            else:
                self.log_test("Dashboard Stats", False, f"Status {resp.status_code}")
                return None
        except Exception as e:
            self.log_test("Dashboard Stats", False, f"Error: {str(e)}")
            return None

    def test_bc_orders(self):
        """Test Business Central sales orders"""
        print("\n🏢 Testing Business Central Integration...")
        try:
            # Test listing all orders
            resp = requests.get(f"{self.api}/bc/sales-orders", headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                orders = data.get("orders", [])
                self.log_test("BC Sales Orders List", True, f"Found {len(orders)} orders")
                
                # Test searching for SO-1001
                resp2 = requests.get(f"{self.api}/bc/sales-orders?search=SO-1001", 
                                   headers=self.headers, timeout=10)
                if resp2.status_code == 200:
                    search_data = resp2.json()
                    search_orders = search_data.get("orders", [])
                    if search_orders:
                        order = search_orders[0]
                        self.log_test("BC Order Search", True, 
                                    f"Found SO-1001: {order['customerName']}")
                        return order
                    else:
                        self.log_test("BC Order Search", False, "SO-1001 not found")
                        return orders[0] if orders else None
                else:
                    self.log_test("BC Order Search", False, f"Status {resp2.status_code}")
                    return orders[0] if orders else None
            else:
                self.log_test("BC Sales Orders List", False, f"Status {resp.status_code}")
                return None
        except Exception as e:
            self.log_test("BC Sales Orders", False, f"Error: {str(e)}")
            return None

    def test_upload_document(self, order_info=None):
        """Test document upload"""
        print("\n📤 Testing Document Upload...")
        try:
            # Create test file content
            sample_content = b"%PDF-1.4\nSample test invoice for GPI Document Hub\nTest content for upload validation"
            
            files = {"file": ("test-invoice-so-1001.pdf", sample_content, "application/pdf")}
            data = {
                "document_type": "SalesOrder",
                "source": "manual_upload"
            }
            
            if order_info:
                data["bc_document_no"] = order_info["number"]
                data["bc_record_id"] = order_info["id"]
            
            resp = requests.post(f"{self.api}/documents/upload", 
                               files=files, data=data, headers=self.headers, timeout=30)
            
            if resp.status_code == 200:
                result = resp.json()
                doc = result["document"]
                workflow_id = result["workflow_id"]
                
                success_details = (f"Document ID: {doc['id'][:8]}..., "
                                 f"Status: {doc['status']}, "
                                 f"Workflow: {workflow_id[:8]}...")
                
                if doc.get('sharepoint_share_link_url'):
                    success_details += f", SharePoint: Connected"
                
                self.log_test("Document Upload", True, success_details)
                return doc
            else:
                self.log_test("Document Upload", False, f"Status {resp.status_code}: {resp.text}")
                return None
        except Exception as e:
            self.log_test("Document Upload", False, f"Error: {str(e)}")
            return None

    def test_document_detail(self, doc_id):
        """Test document detail retrieval"""
        print("\n📋 Testing Document Detail...")
        try:
            resp = requests.get(f"{self.api}/documents/{doc_id}", headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                doc = data["document"]
                workflows = data.get("workflows", [])
                
                self.log_test("Document Detail", True, 
                            f"Retrieved doc: {doc['file_name']}, {len(workflows)} workflows")
                return data
            else:
                self.log_test("Document Detail", False, f"Status {resp.status_code}")
                return None
        except Exception as e:
            self.log_test("Document Detail", False, f"Error: {str(e)}")
            return None

    def test_documents_list(self):
        """Test documents listing"""
        print("\n📄 Testing Document Queue...")
        try:
            resp = requests.get(f"{self.api}/documents", headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                docs = data.get("documents", [])
                total = data.get("total", 0)
                
                self.log_test("Document List", True, f"Retrieved {len(docs)} of {total} documents")
                return docs
            else:
                self.log_test("Document List", False, f"Status {resp.status_code}")
                return None
        except Exception as e:
            self.log_test("Document List", False, f"Error: {str(e)}")
            return None

    def test_settings_status(self):
        """Test settings/status endpoint"""
        print("\n⚙️  Testing Settings...")
        try:
            resp = requests.get(f"{self.api}/settings/status", headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                settings = resp.json()
                connections = settings.get("connections", {})
                
                connection_status = []
                for service, info in connections.items():
                    status = info.get("status", "unknown")
                    connection_status.append(f"{service}: {status}")
                
                self.log_test("Settings Status", True, 
                            f"Demo: {settings.get('demo_mode')}, " + ", ".join(connection_status))
                return settings
            else:
                self.log_test("Settings Status", False, f"Status {resp.status_code}")
                return None
        except Exception as e:
            self.log_test("Settings Status", False, f"Error: {str(e)}")
            return None

    def test_settings_config_endpoints(self):
        """Test new settings configuration endpoints"""
        print("\n🔧 Testing Settings Configuration...")
        
        # Test GET /api/settings/config
        try:
            resp = requests.get(f"{self.api}/settings/config", headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                config_data = resp.json()
                config = config_data.get('config', {})
                
                # Check that config contains expected keys
                expected_keys = {'TENANT_ID', 'BC_ENVIRONMENT', 'BC_CLIENT_ID', 'GRAPH_CLIENT_ID', 'DEMO_MODE'}
                found_keys = set(config.keys())
                has_required_keys = expected_keys.issubset(found_keys)
                
                # Check that secrets are masked
                secrets_masked = True
                secret_keys = ['BC_CLIENT_SECRET', 'GRAPH_CLIENT_SECRET']
                for secret_key in secret_keys:
                    value = config.get(secret_key, '')
                    if value and '****' not in str(value):
                        secrets_masked = False
                
                self.log_test("GET settings/config", has_required_keys and secrets_masked,
                            f"Keys found: {len(found_keys)}/{len(expected_keys)}, Secrets masked: {secrets_masked}")
            else:
                self.log_test("GET settings/config", False, f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            self.log_test("GET settings/config", False, f"Error: {str(e)}")

        # Test PUT /api/settings/config
        try:
            test_config = {
                "TENANT_ID": "test-tenant-123-456",
                "BC_ENVIRONMENT": "TestEnviroment", 
                "BC_COMPANY_NAME": "Test Company Limited"
            }
            resp = requests.put(f"{self.api}/settings/config",
                              json=test_config,
                              headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                response_data = resp.json()
                updated_config = response_data.get('config', {})
                tenant_updated = updated_config.get('TENANT_ID') == 'test-tenant-123-456'
                env_updated = updated_config.get('BC_ENVIRONMENT') == 'TestEnviroment'
                has_message = 'message' in response_data
                
                self.log_test("PUT settings/config", tenant_updated and env_updated and has_message,
                            f"TENANT_ID: {tenant_updated}, BC_ENVIRONMENT: {env_updated}, Message: {has_message}")
            else:
                self.log_test("PUT settings/config", False, f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            self.log_test("PUT settings/config", False, f"Error: {str(e)}")

        # Test POST /api/settings/test-connection?service=graph
        try:
            resp = requests.post(f"{self.api}/settings/test-connection?service=graph",
                               headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                test_data = resp.json()
                service_correct = test_data.get('service') == 'graph'
                has_status = 'status' in test_data
                has_detail = 'detail' in test_data
                
                self.log_test("POST test-connection graph", service_correct and has_status and has_detail,
                            f"Service: {test_data.get('service')}, Status: {test_data.get('status')}")
            else:
                self.log_test("POST test-connection graph", False, f"HTTP {resp.status_code}")
        except Exception as e:
            self.log_test("POST test-connection graph", False, f"Error: {str(e)}")

        # Test POST /api/settings/test-connection?service=bc  
        try:
            resp = requests.post(f"{self.api}/settings/test-connection?service=bc",
                               headers=self.headers, timeout=10)
            
            if resp.status_code == 200:
                test_data = resp.json()
                service_correct = test_data.get('service') == 'bc'
                has_status = 'status' in test_data
                has_detail = 'detail' in test_data
                
                self.log_test("POST test-connection bc", service_correct and has_status and has_detail,
                            f"Service: {test_data.get('service')}, Status: {test_data.get('status')}")
            else:
                self.log_test("POST test-connection bc", False, f"HTTP {resp.status_code}")
        except Exception as e:
            self.log_test("POST test-connection bc", False, f"Error: {str(e)}")

    def run_all_tests(self):
        """Run complete test suite"""
        print("=" * 80)
        print("GPI Document Hub - Backend API Test Suite")
        print(f"Testing: {self.base_url}")
        print("=" * 80)

        # Test authentication first
        if not self.test_login():
            print("\n❌ Authentication failed - stopping tests")
            return False

        # Run all other tests
        self.test_auth_me()
        stats = self.test_dashboard_stats()
        order = self.test_bc_orders()
        
        # Upload and document tests
        uploaded_doc = self.test_upload_document(order)
        if uploaded_doc:
            self.test_document_detail(uploaded_doc["id"])
        
        self.test_documents_list()
        self.test_settings_status()
        self.test_settings_config_endpoints()

        # Print final results
        print("\n" + "=" * 80)
        print("TEST RESULTS")
        print("=" * 80)
        print(f"Tests Run: {self.tests_run}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%")
        
        if self.tests_passed == self.tests_run:
            print("\n🎉 ALL TESTS PASSED! Backend is functioning correctly.")
            return True
        else:
            print(f"\n⚠️  {self.tests_run - self.tests_passed} test(s) failed.")
            
            # Show failed tests
            failed_tests = [t for t in self.test_results if not t["success"]]
            if failed_tests:
                print("\nFailed Tests:")
                for test in failed_tests:
                    print(f"  ❌ {test['name']}: {test['details']}")
            
            return False

def main():
    tester = GPIDocumentHubTester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())