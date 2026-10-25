LAB BUDGET TRACKER - INTRANET VERSION
=====================================

WHAT YOU NEED (ask hospital IT)
- A PC or server on the hospital network that stays switched on.
- Python 3.8 or newer installed (python.org). No other software or internet needed.

INSTALL
1. Copy this whole folder to the server (for example C:\BudgetTracker).
2. Open a Command Prompt in this folder and run:  python server.py   (Linux: python3 server.py)
   Optional shortcut for Windows: rename start-bat.txt to start.bat, then double-click it.
   (The .bat file was sent as .txt because email systems block .bat attachments.)
3. On first run a window shows the admin username and a one-time password. Write it down.
4. On any computer in the hospital network open:  http://SERVER-NAME-OR-IP:8080
   (IT may need to allow port 8080 in the server firewall, or set another port: set PORT=9000 before starting.)
5. Sign in as admin, click "Change password" (top right), then open Accounts.

ONE TRACKER, TWO VOTES (REAGENTS 27403 AND CONSUMABLES 27499)
- One program, one port, one database file (budget.db), one set of accounts. Use the "Vote" switch at the top of the page to move between Reagents (27403) and Consumables (27499).
- Each vote has its own budget, units, LPOs, stock, warrants, reconciliation, team assignments and new-year step. Nothing is mixed between votes.
- A unit head can be assigned to different units in each vote (Team tab, while that vote is selected). Admins (PIC / HOD) see both votes.
- The consumables vote has no Cost per test tab.
- Existing data from an earlier installation becomes the Reagents vote automatically. Consumables starts with sample figures; replace them in Setup.
- Export data file and Start new year work on the vote that is currently selected. Download backup copies the whole database (both votes).

SET UP PEOPLE
- Accounts tab: create one login for each person. Role "Admin" for the PIC and HOD. Role "Unit head" for everyone else.
- Team tab: search for the unit head and tick the units they look after. Unit heads then see and change only their own units.
- Forgotten password: Accounts > Reset password.  Someone leaving: Accounts > Disable.

DATA AND BACKUP
- All data is in one file, budget.db, in this folder. Accounts > Download backup gives a full copy.
- Ask IT to copy budget.db to a safe place every day. To restore, stop the program and put the backup in as budget.db.
- The program starts with sample figures. Replace them in Setup before real use.

NEW YEAR (admin only, once a year)
- Do the December stock count and record it first. Choose a time when nobody else is using the system.
- Setup > "Start new year...". Enter the new year and total budget, check the unit shares, tick the box and confirm.
- A full backup downloads first. Keep it. The old year's records are also kept inside budget.db (table "archive").
- Cleared: LPOs, requests, reconciliations, test counts, stock movements. Carried forward: stock items and lots (with expiry), unspent warrant money, accounts and unit assignments.

EXPORT DATA FILE (optional)
- Accounts > "Export data file" downloads one .json file with the selected vote's budget, LPO, stock and test data. Passwords and team assignments are not included.
- Keep this file inside the hospital. Do not upload hospital data to outside services unless hospital IT has approved it.

LOADING THE EXCEL LPO SHEET (PERUNTUKAN) - runs on the server, data never leaves the hospital
- First, in the tracker's Setup tab, enter the budget and the units for each vote. The unit names must match colours.json (Biokimia, Hematologi, Mikrobiologi, Histositologi, POCT), or edit colours.json to match your names.
- Put the Excel file in this folder. Dry run (writes nothing):
      python load_peruntukan.py PERUNTUKAN.xlsx --user admin
  It asks for the tracker admin password, then prints a summary and writes import_review.csv.
- Open import_review.csv. Rows marked "skipped" need attention: cancelled or redundant rows, rows with no LO number, a missing or wrong-year date, a colour not in colours.json, or an LO number entered twice with the same amounts. Fix them in the Excel sheet and run the dry run again.
- When it looks right, load for real:
      python load_peruntukan.py PERUNTUKAN.xlsx --user admin --commit
- Sheet 27403 goes to the Reagents vote and sheet 27499 to the Consumables vote. A row coloured for a section goes to that section. A row with Tanggungan is loaded as an LPO without an invoice. A row with Sebenar is loaded as an LPO with that invoice amount. The remarks text is kept in the Item field.
- Running it again is safe: the same LPO is overwritten, not duplicated. Use --url http://SERVER:PORT if the tracker is not on port 8080, and --year 2027 next year.
- It loads LPOs only. Budgets, top-ups and stock are entered in the tracker.

DOCUMENT PORTAL (ISO) - the "Dokumen ISO" link at the top
- A controlled register of laboratory documents: quality manual, policies, SOPs, work instructions, forms, external documents and memos. It is shared by the whole laboratory (it does not depend on the budget vote).
- Accounts: create a login for every staff member under Accounts. Role "Staff (documents only)" sees only the document portal. Unit heads and admins can use it as well.
- Admins (PIC / HOD) add documents: document number, title, category, section, version, effective date, how often to review (default 24 months), owner, keywords and the file (PDF, Word, Excel, PowerPoint, image, txt or csv, up to 25 MB). Tick "Important" to highlight a document. A new document starts as Draft. Staff cannot see drafts.
- "Approve" makes it visible to staff and turns the earlier approved version of the same document number into Obsolete. Obsolete versions are kept for the record but staff cannot open them. "New version" copies the details and asks for the next version number and the new file.
- Staff press "I have read this" on each approved version. Admins see "Read by X/Y" and can list who has not read it.
- Admins get alerts for documents whose review date is overdue or within 60 days.
- Search by number, title, category, section or keywords. The microphone button gives voice search; on a plain http address Chrome blocks the microphone unless the server address is allowed under "Insecure origins treated as secure" in chrome://flags.
- "Download master list (CSV)" gives the register of documents with version, status, effective and review dates.
- Files are stored inside budget.db, so the daily copy of budget.db backs up the documents as well. Expect it to grow.
- The search looks at the document details, not the text inside the files.

UPDATING AN EXISTING INSTALLATION
- Stop the program, replace server.py and index.html with the new ones, start it again. Do NOT replace or delete budget.db. Copy budget.db first as a precaution.

KEEP IT RUNNING
- IT can start server.py automatically when the server boots (Windows Task Scheduler "At startup", or a service tool such as NSSM).

SECURITY NOTES FOR IT
- Passwords are stored hashed (PBKDF2). Sessions last 12 hours. 5 wrong passwords lock the account for 5 minutes.
- Access rules are enforced on the server, not only in the page. Unit heads cannot read or write other units' records.
- Traffic is plain HTTP. If the hospital requires HTTPS, put the program behind the hospital's web server or reverse proxy.
- Unit heads can read the overall budget and unit allocations (the page needs them to work).

EXCEL IMPORT
- CSV and pasted rows work as they are. To import .xlsx files directly, IT can place the file xlsx.full.min.js (SheetJS 0.18.5, downloaded once from cdnjs.cloudflare.com) in this folder.

LIMITS
- This is a working copy for the laboratory, not a hospital-approved financial system. Check with hospital IT and finance before using it for official records.
- Pages refresh by checking the server every few seconds. There is no email or WhatsApp alert; alerts show when someone opens the page.
