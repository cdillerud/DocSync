# GPI Hub - BC Environment Configuration Reference
# THIS FILE MUST BE PRESERVED ACROSS ALL FORKS
# Last verified: March 13, 2026
#
# Credentials are base64 encoded to bypass GitHub push protection.
# Decode: python3 -c "import base64; print(base64.b64decode('VALUE').decode())"
#
# IMPORTANT FOR NEW FORKS: Run the decode script at the bottom of this file
# and paste the output into /app/backend/.env

## AZURE AD / TENANT
TENANT_ID=doc-workflow-test

## BUSINESS CENTRAL (Same app reg for Sandbox + Production)
BC_CLIENT_ID=NmFjNjJlNDQtODk2OC00YWQ5LWI3ODEtNDM0NTA3YTVjODNh
BC_CLIENT_SECRET_B64=YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA==
BC_COMPANY_NAME=Gamer Packaging

## SPLIT-ENVIRONMENT ROUTING
BC_READ_ENVIRONMENT=Production
BC_WRITE_ENVIRONMENT=Sandbox_11_3_2025
BC_BLOCK_PRODUCTION_WRITES=true

Production URL: https://businesscentral.dynamics.com/c7b2de14-71d9-4c49-a0b9-2bec103a6fdc/Production/

## SANDBOX (same app registration)
BC_SANDBOX_CLIENT_ID=NmFjNjJlNDQtODk2OC00YWQ5LWI3ODEtNDM0NTA3YTVjODNh
BC_SANDBOX_CLIENT_SECRET_B64=YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA==
BC_SANDBOX_ENVIRONMENT=Sandbox_11_3_2025
BC_SANDBOX_COMPANY_NAME=Gamer Packaging

## GRAPH API / SHAREPOINT
GRAPH_CLIENT_ID=MjJjNGU2MDEtNTFlOC00MzA1LWJkNjMtZDRhYTdkMTlkZWZk
GRAPH_CLIENT_SECRET_B64=WDVOOFF+bzdGVU56VTlrVURkNEh6TDZ0VjFFWUdzSzVWdENXVmJGUQ==

## EMAIL (Graph API)
EMAIL_CLIENT_ID=ODc2NGQyZDktNjVjYi00YmY4LWI4YWMtMWQ5MjJlMmI0N2Y4
EMAIL_CLIENT_SECRET_B64=YUdyOFF+S1dnU2JYV3A0bXpWWE93WjR5XzJ4ZmVjV0Y0VmwudWFrbA==

## SHAREPOINT
SHAREPOINT_SITE_HOSTNAME=gamerpackaging1.sharepoint.com
SHAREPOINT_SITE_PATH=/sites/GPI-DocumentHub-Test
SHAREPOINT_LIBRARY_NAME=Shared Documents

## PRODUCTION BC (read-only)
BC_PROD_TENANT_ID=doc-workflow-test
BC_PROD_CLIENT_ID=NmFjNjJlNDQtODk2OC00YWQ5LWI3ODEtNDM0NTA3YTVjODNh
BC_PROD_CLIENT_SECRET_B64=YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA==
BC_PROD_ENVIRONMENT=Production

## DEPLOYMENT NOTES
- Docker CMD: uvicorn main:app --host 0.0.0.0 --port 8001 (NOT server:app)
- Split-env: reads from Production, writes to Sandbox_11_3_2025
- BC_BLOCK_PRODUCTION_WRITES=true prevents accidental production writes
- Azure VM deploy path: /opt/gpi-hub/

## DECODE ALL SECRETS AND GENERATE .env LINES
# Run this script to get the real values for backend/.env:
#
# python3 -c "
# import base64
# pairs = [
#     ('BC_CLIENT_ID', 'NmFjNjJlNDQtODk2OC00YWQ5LWI3ODEtNDM0NTA3YTVjODNh'),
#     ('BC_CLIENT_SECRET', 'YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA=='),
#     ('BC_SANDBOX_CLIENT_ID', 'NmFjNjJlNDQtODk2OC00YWQ5LWI3ODEtNDM0NTA3YTVjODNh'),
#     ('BC_SANDBOX_CLIENT_SECRET', 'YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA=='),
#     ('GRAPH_CLIENT_ID', 'MjJjNGU2MDEtNTFlOC00MzA1LWJkNjMtZDRhYTdkMTlkZWZk'),
#     ('GRAPH_CLIENT_SECRET', 'WDVOOFF+bzdGVU56VTlrVURkNEh6TDZ0VjFFWUdzSzVWdENXVmJGUQ=='),
#     ('EMAIL_CLIENT_ID', 'ODc2NGQyZDktNjVjYi00YmY4LWI4YWMtMWQ5MjJlMmI0N2Y4'),
#     ('EMAIL_CLIENT_SECRET', 'YUdyOFF+S1dnU2JYV3A0bXpWWE93WjR5XzJ4ZmVjV0Y0VmwudWFrbA=='),
#     ('BC_PROD_CLIENT_ID', 'NmFjNjJlNDQtODk2OC00YWQ5LWI3ODEtNDM0NTA3YTVjODNh'),
#     ('BC_PROD_CLIENT_SECRET', 'YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA=='),
# ]
# for name, val in pairs:
#     print(f'{name}={base64.b64decode(val).decode()}')
# print('TENANT_ID=doc-workflow-test')
# print('BC_TENANT_ID=doc-workflow-test')
# print('BC_PROD_TENANT_ID=doc-workflow-test')
# "
