# Equipment Invoice Capture — Setup & Automation Guide

Companion to **Invoice_Tracker_Template.xlsx**. Goal: every invoice captured by
**Store → Equipment Type → Cost**, refreshed weekly, ready for trend analysis.

---

## 0. Big picture — TWO sources feed one table

Both write into the same `tblInvoices` table (one row per equipment line item).

| Source | What it is | Best for | Effort |
|---|---|---|---|
| **A. Owl Ops export** (primary) | CSV/Excel exported from Owl Ops' Reports/Invoicing area | The bulk of invoices — already tagged with store, asset, vendor, cost, status | Low / repeatable |
| **B. Forwarded-email flow** (supplement) | Power Automate + AI Builder reads PDF invoices from forwarded emails | Invoices not (yet) in Owl Ops; real-time capture | One-time setup |

> Rule of thumb: if it's in Owl Ops, **export it** — structured data beats OCR.
> Use the email flow for the gaps.

---

## 1. Put the template in place (once)

1. Upload `Invoice_Tracker_Template.xlsx` to **OneDrive** or **SharePoint** (so Excel-for-web + Power Automate can both reach it).
2. On **Stores**, **Equipment Types**, **Vendors** — replace the sample rows with your real lists. The drop-downs and charts read from these.
3. On **Invoices** — delete the 8 sample rows (they exist only to demo the charts).

---

## 2. Source A — Owl Ops export (do this first; it's the bulk)

**In Owl Ops:** open **Reports** (or **Invoicing → Invoices**), filter to a date range
(e.g., last 7 days), and **Export** to CSV/Excel.

**Load it into the workbook — two options:**

- **(a) Power Query — recommended, repeatable.** In the workbook:
  `Data → Get Data → From File`, point at the export, in the editor rename/reorder
  columns to match `tblInvoices`, then **Close & Load** (append). Each week you just
  drop in the new export and hit **Refresh**. I'll build this query for you once you
  send me the export's column headers.
- **(b) Manual paste** for now: copy the export rows under the table; the Week/Month
  columns auto-fill.

**Mapping (Owl Ops → tblInvoices):** Location → **Store**, Asset/Equipment → **Equipment
Type**, Work-order type → **Category**, Invoice total/line → **Line Total ($)**,
Provider → **Vendor**, Invoice # / date / status map 1:1. (Exact left-side names depend
on your export — send me the header row and I'll finalize it.)

---

## 3. Source B — Power Automate flow (forwarded invoice emails)

### 3.1  Prep Outlook
Create a folder **Invoices** and an Outlook rule that moves forwarded invoices into it
(e.g., from your AP address or subject contains "invoice"). The flow watches that folder.

### 3.2  Trigger
**Office 365 Outlook → "When a new email arrives (V3)"**
- **Folder:** Invoices
- **Include Attachments:** Yes
- **Only with Attachments:** Yes

### 3.3  Handle the forward
A forwarded vendor invoice normally carries the original **PDF as an attachment**, so we
work from the `Attachments` array.
- Add **Apply to each** → `Attachments`
- Inside, a **Condition**: `Attachments Name` ends with `.pdf` (skip logos/signatures)
- *(If your invoices are inline in the body with no PDF, instead pass the email **Body**
  to the AI prompt in 3.5 — tell me and I'll give you that variant.)*

### 3.4  Extract the invoice
**AI Builder → "Extract information from invoices"**
- **Invoice file:** `Attachments Content`
- Gives you: Invoice ID, Invoice date, Vendor name, Invoice total, **Service address**,
  and a line-item table **Items** (Description, Quantity, Unit price, Amount).

### 3.5  Derive the two "smart" fields
These aren't clean fields on most invoices:
- **Store** — from the **Service address** output (or a store # in the subject). Use a
  **Switch** (or a lookup against the Stores sheet) to turn it into your Store name.
- **Equipment Type** — classify each line item's **Description** with an AI prompt.
  Add **AI Builder → "Run a prompt"** (a.k.a. *Create text with GPT*) using the prompt in
  §4, input = `Items Description`. Output = the matched Equipment Type.

### 3.6  Write to the workbook
**Excel Online (Business) → "Add a row into a table"**
- **Location/Library/File:** your OneDrive copy → **Table:** `tblInvoices`
- For multi-item invoices, do this **inside an Apply to each over `Items`** (one row per item).
- Field mapping:

| tblInvoices column | Value |
|---|---|
| Invoice Date | Invoice date (date) |
| Store | (from §3.5 Switch) |
| Equipment Type | (from §3.5 prompt) |
| Category | set a default e.g. `Repair`, or classify too |
| Line Total ($) | `Items Amount` |
| Vendor | Vendor name |
| Invoice # | Invoice ID |
| Description | `Items Description` |
| Qty | `Items Quantity` |
| Unit Price ($) | `Items Unit price` |
| Tax ($) | Total tax (or blank per-line) |
| Status | `Pending` |
| Date Captured | `utcNow()` |
| Invoice File | (optional) link to the saved PDF |

*(Leave Week Of / Month blank — Excel fills those automatically.)*

### 3.7  Optional hardening
- **Approval first:** add an **Approvals → Start and wait for an approval** before the
  write if a human should sign off.
- **No duplicates:** key on Invoice #. Either *List rows present in a table* + Condition,
  or use the Office Script in Appendix A as an upsert.

### 3.8  Weekly vs real-time
Per-email (the trigger above) is simplest and is effectively "weekly-plus." For a true
**weekly batch**, swap the trigger for **Recurrence (weekly)** + **"Get emails (V3)"**
filtered to the last 7 days, then loop the results.

---

## 4. Equipment-classification prompt (paste into the AI prompt action)

```
You categorize maintenance/repair invoice line items for a multi-location
restaurant business. Read the line-item description and return ONLY the single
best-matching equipment type from the list below — return the text verbatim,
nothing else. If nothing clearly matches, return "Other".

Allowed equipment types:
Fryer; Range / Oven; Grill / Griddle; Hood / Exhaust Fan; Walk-in Cooler;
Reach-in Freezer; Ice Machine; Soda / Beverage Fountain; Coffee Machine;
Dishwasher; Grease Trap; Water Heater; Rooftop HVAC Unit; Mini-split AC;
POS Terminal; Receipt Printer; Security / CCTV; Lighting / Electrical

Line-item description: {Items Description}
```

Keep this list identical to your **Equipment Types** sheet so classifications match the drop-down.

---

## 5. Trend analysis (already wired)

- **Trends** sheet updates automatically (cost by store, equipment, category, month).
- For ad-hoc slicing, click any cell in `tblInvoices` → **Insert → PivotTable** → drag
  Store / Equipment Type / Month onto rows and **Line Total ($)** onto values. This is the
  Owl Ops-style "slice by any dimension."
- Later, point **Power BI** at the same table for shareable dashboards.

---

## 6. Send me this and I'll finish it

1. The **header row** (column names) of an Owl Ops invoice export — or a sample export file.
2. **One sample forwarded invoice** (de-identified is fine) so I can confirm the field mapping.
3. Your real **store list**, **equipment categories**, and **vendors** (or confirm you'll type them in).

With #1 I'll build the **Power Query importer**; with #2 I'll lock the **flow field mapping**.

---

## Appendix A — Office Script for de-duped insert (optional)

In Excel for the web: **Automate → New Script**, paste, save as **AddInvoiceRow**, then in
Power Automate use **Excel Online (Business) → Run script** instead of "Add a row."

```typescript
function main(
  workbook: ExcelScript.Workbook,
  invoiceDate: string, store: string, equipment: string, category: string,
  lineTotal: number, vendor: string, invoiceNo: string, description: string,
  qty: number, unitPrice: number, tax: number, status: string
) {
  const table = workbook.getTable("tblInvoices");
  // de-dupe on Invoice # + Description
  const rows = table.getRangeBetweenHeaderAndTotal().getValues();
  const exists = rows.some(r => `${r[8]}` === invoiceNo && `${r[9]}` === description);
  if (exists) return;
  table.addRow(-1, [
    invoiceDate, "", "", store, equipment, category, lineTotal, vendor,
    invoiceNo, description, qty, unitPrice, tax, status, "", "", "",
    new Date().toISOString().slice(0, 10), ""
  ]);
}
```

(Columns B/C are left empty on purpose — the Week/Month formulas fill them.)
