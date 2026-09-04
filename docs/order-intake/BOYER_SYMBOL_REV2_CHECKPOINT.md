# Boyer Symbol Inspection REV2 Checkpoint

Date: 2026-09-03

The first GET-only Boyer symbol inspection successfully passed all PRE/environment/company/app safety gates and downloaded the target symbol package, then failed locally because PowerShell could not resolve `FullName` on an archive entry under strict mode.

REV2 is implemented in `scripts/Inspect-GPIOrderIntakeBoyerSymbols-PRE-REV2.ps1`.

REV2 changes only local package inspection:
- exact PRE sandbox/company and installed-app pins retained
- BC operations remain GET only
- no extension mutation
- no business-data read/write
- no Sales Order action
- no Production access
- archive entry names and lengths are obtained through .NET reflection rather than the PowerShell property adapter
- archive-entry runtime type and package header evidence are returned on local inspection failure
- temporary downloaded package is deleted in `finally`

No Business Central write test is authorized by this checkpoint.
