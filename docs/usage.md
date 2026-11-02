# Using net-month

## Import and review

Choose **Import CSV**, select or drop an export, inspect the preview, then confirm. Exact overlaps are preselected to skip one-for-one. Possible duplicates and repeated identical rows need your choice because exports may lack stable transaction IDs. Two identical real purchases can both be retained.

A matching imported transaction can replace a manual entry while retaining its category, monthly allocations, notes and credit links. Original exports are preserved; confirmed imports are also retained under `data/imports/`.

Use **Review** to classify uncertain transactions, link credits and confirm categories with no spending. Payments and transfers remain searchable but are excluded from spending. Mark a month reviewed when its coverage is complete. Later changes reopen it as a draft.

## Annual costs and irregular expenses

Edit an expense and use **Split evenly**, or enter its allocation months and amounts. Allocations must add up to the full original charge. Imported dates and amounts stay unchanged. A manual expense uses a negative amount; a refund or repayment uses a positive amount.

Monthly actuals show allocated expenses less linked credits. These figures describe how you assign costs across months; they are not a statement of cash moving through your bank account that month.

## Refunds and reimbursements

Set a credit's treatment to Refund or Reimbursement, save, then choose **Link credit**. Match it to the original expense. One credit can cover several expenses; one expense can receive several credits, up to its original amount.

Credits reduce the original expense's allocation months proportionally. A $240 refund against a $1,200 expense allocated evenly across twelve months reduces each month by $20. A partial credit remains in Review until all of that received credit is linked. Suggestions never silently match repeated purchases.

## Subscriptions, budgets and months

The app detects the same vendor and exact charge in consecutive calendar months, allowing billing dates to shift by up to seven days and 20–40 days between charges. Ambiguous repeated charges, manually classified transactions, and fully refunded expenses do not establish a new automatic subscription. Detection is limited to the configured subscription/fallback categories and unclassified transactions. Substantial merchant-name changes require manual review.

Detection rechecks earlier imports and runs after edits or credit links. Automatic categories can change when evidence changes; manually saved classifications remain yours. Splitting an annual payment across months does not turn it into recurring monthly evidence.

Edit a month's budget to change that month. New months inherit the preceding plan. Use **Manage months** to hide months temporarily in the current browser tab or exclude them until restored. Neither option deletes data. **All months, including hidden** still searches every transaction.

## Records and recovery

`data/dashboard_data.csv` holds transactions, allocations, links, budgets, month settings and import records. `data/config.json` holds your category configuration. Keep them together when moving the app or restoring records.

Saves keep the latest 30 CSV backups under `data/backups/`. To restore one, stop the server, preserve the current CSV and matching configuration, copy the chosen backup to `data/dashboard_data.csv`, then restart. A CSV download is also available under **Your data**.

If a save reports **Saved · reload needed**, the write completed but the display failed to refresh. Reload it. **Save unconfirmed** means the response was lost; reload and check for the entry before entering it again. A revision conflict means another window changed the data; reloading discards the open draft. Rejected edits keep the draft and show the error.
