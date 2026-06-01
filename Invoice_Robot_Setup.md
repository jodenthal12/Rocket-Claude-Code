# Set Up the Invoice Robot — One Time, ~30 Minutes

**What you'll have when done:** an invoice lands in your Outlook → a row appears on the
**Invoices** tab of your tracker, by itself. Forever. You don't touch it.

You only do this setup **once**. Take it slow — it's just clicking.

---

## Before you start (5 min)

1. **Put the tracker in OneDrive.** Open `Invoice_Tracker_Template.xlsx`, and save it to
   **OneDrive** (File → Save As → OneDrive). The robot can only reach it if it lives in the cloud.
2. **Make an Outlook folder** called **Invoices**. (In Outlook: right-click your inbox → New Folder.)
3. **Make a rule** so invoice emails go into that folder automatically:
   Outlook → Settings → **Rules** → Add new rule → "If subject contains *invoice*" (or "from
   *your vendors*") → "Move to folder **Invoices**." Save.

That's the prep. Now the robot.

---

## Build the robot (Power Automate)

### Step 1 — Open Power Automate
Go to **make.powerautomate.com** and sign in with your work email (the same one with Outlook).

### Step 2 — Start a new flow
- Left menu → **+ Create**
- Click **Automated cloud flow**
- Flow name: type `Invoice to Tracker`
- In the search box, find **"When a new email arrives (V3)"** → click it → **Create**

### Step 3 — Tell it which emails to watch
In the box that appears:
- **Folder:** click the folder icon → choose **Invoices**
- Click **Show advanced options** (or the dropdown) and set:
  - **Only with Attachments:** Yes
  - **Include Attachments:** Yes

### Step 4 — Add the invoice reader
- Click the **+** under that box → **Add an action**
- Search: **Extract information from invoices** → click it
- *(If it asks to turn on an **AI Builder** trial, say **Yes** — it's free for 30 days. After
  that it's a small paid add-on; I'll tell you the cost if you want it.)*
- In the **Invoice file** box → click the little **lightning bolt** (dynamic content) →
  choose **Attachments Content**
- A grey **"Apply to each"** box wraps around it — **that's normal**, leave it.

### Step 5 — Send it to your tracker
- **Inside** that grey box, click **+** → **Add an action**
- Search: **Add a row into a table** → click it (the **Excel Online (Business)** one)
- Fill the top boxes:
  - **Location:** OneDrive for Business
  - **Document Library:** OneDrive
  - **File:** click the folder icon → pick your tracker
  - **Table:** choose **tblInvoices**
- Now boxes appear for each column. Fill them from the invoice reader's results
  (click the lightning bolt in each box and pick the matching item):

| Tracker box | Pick this |
|---|---|
| Invoice Date | **Invoice date** |
| Cost ($) | **Invoice total** (the number one) |
| Vendor | **Vendor name** |
| Invoice # | **Invoice ID** |
| Store | **Service address** *(you'll confirm the store name later)* |
| Equipment Type | just type the word: `Review` |
| Status | just type: `Pending` |
| Date Captured | click lightning bolt → **Expression** tab → type `utcNow()` → OK |
| Description / Month / Notes / Source | leave blank |

### Step 6 — Save
Click **Save** (top right). The robot is live.

---

## Test it (2 min)
Forward yourself any invoice (or a sample PDF) so it lands in the **Invoices** Outlook folder.
Wait about a minute, then open your tracker → **Invoices** tab. **A new row should appear.** 🎉

---

## What's automatic vs. your 10 seconds

| The robot fills automatically | You do (≈10 sec/invoice, once a week) |
|---|---|
| Date, Cost, Vendor, Invoice # | Pick the **Equipment Type** from the dropdown |
| Drops it on the Invoices tab | Confirm the **Store** (fix if the address didn't match) |
| Charts on Trends update | — |

That's the honest "you barely lift a finger" version.

---

## Want truly zero-touch? (optional Level 2)
We can add two more steps so even those 10 seconds disappear:
- **Auto-pick Equipment Type** — an AI step reads the invoice wording and chooses the type.
- **Auto-match Store** — turns the address into your exact store name.

Say the word and I'll write the add-on steps. I'd suggest getting Level 1 running first.

---

## If something doesn't work
- **No row appeared?** In Power Automate → **My flows** → click your flow → check **Run history**
  for a red X, and tell me what it says.
- **Invoices are inside the email text, not a PDF attachment?** Tell me — that needs a slightly
  different Step 4, and I'll give it to you.
