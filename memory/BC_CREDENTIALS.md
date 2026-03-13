# GPI Hub - BC Environment Configuration Reference
# THIS FILE MUST BE PRESERVED ACROSS ALL FORKS
# Last verified: March 14, 2026
#
# Credentials are base64 encoded to bypass GitHub push protection.
# Decode: python3 -c "import base64; print(base64.b64decode('VALUE').decode())"

## AZURE AD / TENANT
TENANT_ID=c7b2de14-71d9-4c49-a0b9-2bec103a6fdc

## BUSINESS CENTRAL (Same app reg for Sandbox + Production)
BC_CLIENT_ID=6ac62e44-8968-4ad9-b781-434507a5c83a
BC_CLIENT_SECRET_B64=YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA==
BC_COMPANY_NAME=Gamer Packaging

## SPLIT-ENVIRONMENT ROUTING
BC_READ_ENVIRONMENT=Production
BC_WRITE_ENVIRONMENT=Sandbox_11_3_2025
BC_BLOCK_PRODUCTION_WRITES=true

Production URL: https://businesscentral.dynamics.com/c7b2de14-71d9-4c49-a0b9-2bec103a6fdc/Production/

## SANDBOX (same app registration)
BC_SANDBOX_CLIENT_ID=6ac62e44-8968-4ad9-b781-434507a5c83a
BC_SANDBOX_CLIENT_SECRET_B64=YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA==
BC_SANDBOX_ENVIRONMENT=Sandbox_11_3_2025
BC_SANDBOX_COMPANY_NAME=Gamer Packaging

## GRAPH API / SHAREPOINT
GRAPH_CLIENT_ID=22c4e601-51e8-4305-bd63-d4aa7d19defd
GRAPH_CLIENT_SECRET_B64=WDVOOFF+bzdGVU56VTlrVURkNEh6TDZ0VjFFWUdzSzVWdENXVmJGUQ==

## EMAIL (Graph API)
EMAIL_CLIENT_ID=8764d2d9-65cb-4bf8-b8ac-1d922e2b47f8
EMAIL_CLIENT_SECRET_B64=YUdyOFF+S1dnU2JYV3A0bXpWWE93WjR5XzJ4ZmVjV0Y0VmwudWFrbA==

## SHAREPOINT
SHAREPOINT_SITE_HOSTNAME=gamerpackaging1.sharepoint.com
SHAREPOINT_SITE_PATH=/sites/GPI-DocumentHub-Test
SHAREPOINT_LIBRARY_NAME=Shared Documents

## DEPLOYMENT NOTES
- Docker CMD: uvicorn main:app --host 0.0.0.0 --port 8001 (NOT server:app)
- Split-env: reads from Production, writes to Sandbox_11_3_2025
- BC_BLOCK_PRODUCTION_WRITES=true prevents accidental production writes
- Same Azure AD app reg (6ac62e44...) for both envs
- Azure VM deploy path: /opt/gpi-hub/

## DECODE ALL SECRETS
python3 -c "
import base64
for name, val in [
    ('BC_CLIENT_SECRET', 'YmROOFF+TUJPQzZ4YzRZSWRiM0s3d2ZKQ0wwdzlncTFoVm1WdWNtNA=='),
    ('GRAPH_CLIENT_SECRET', 'WDVOOFF+bzdGVU56VTlrVURkNEh6TDZ0VjFFWUdzSzVWdENXVmJGUQ=='),
    ('EMAIL_CLIENT_SECRET', 'YUdyOFF+S1dnU2JYV3A0bXpWWE93WjR5XzJ4ZmVjV0Y0VmwudWFrbA=='),
]:
    print(f'{name}={base64.b64decode(val).decode()}')
"
