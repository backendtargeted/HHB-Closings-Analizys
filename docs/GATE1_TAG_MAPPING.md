# Calling and SMS → REISift mapping

This is the approved monthly Gate 1 mapping policy. Executable rules are in `backend/app/services/marketing_tag_policy.py`; ingestion and conflict handling are in `monthly_marketing.py`. Salesforce and the legacy workflow have separate rules and are not changed by this policy.

Both calling and SMS generate **property statuses, phone statuses, custom phone tags, and dated property activity tags**. Neither requires Salesforce. Property and phone mappings are evaluated independently: an unresolved target does not suppress another supported target. Source labels are never automatically created as custom tags.

## Approved interpretations

| Source label | Property status | Phone status | Custom phone tags |
|---|---|---|---|
| Decision Maker / Decision Maker - Lead | lead | Correct | Correct, Contacted |
| Decision Maker - NYI (Not Yet Interested) | Follow Up | Correct | Correct, Contacted |
| Not Interested | Follow Up | Correct | Contacted |
| Wrong Number | Follow Up | Wrong | Wrong Number |
| Voicemail | Follow Up | No Answer | Voicemail |
| No Answer | Follow Up | No Answer | None |
| Dead Call / Dead Call / Disconnected / Disconnected | Follow Up | Dead | None |
| DNC - Decision Maker (explicit owner opt-out) | dnc | Correct DNC | DNC |
| DNC / DNC - Unknown / Do Not Call | No update | DNC | DNC |
| Sold | sold | Unresolved | None |

Retained supported mappings: New/New Lead/Lead and Callback/Call Back → property `lead`; Follow Up, Spanish Speaker, Influencer, Maybe Later (including SMS suffix), ABV MV (including SMS suffix) → property `Follow Up`; Listed Property/Listed → property `On Market Listing`. These labels map to phone `Correct` with `Contacted`.

Labels without an approved interpretation—including FU1, FU2, Potential, Pushed to Client, Investor, Agent, Bluffer, Prank Voicemail, and Unknown—remain in review for each unresolved target. No additional custom tags are invented. Untouched SMS records and records labeled only Undefined, No Label, or Duplicate do not create activity tags.

## Account vocabulary

Only these active property statuses may be emitted: `Dead Deal`, `dnc`, `lead`, `Appointment`, `Offer Accepted`, `under_contract`, `Committed to List`, `Contract Signed`, `Expired Listing`, `On Market Listing`, `sold`, `buyer`, `prospecting`, `New`, `Not Yet Reached`, `Follow Up`, `Converted`.

Phone statuses: `Correct`, `Correct DNC`, `Wrong`, `Wrong DNC`, `No Answer`, `Dead`, `DNC`. No Status, Untagged, and Primary are filter helpers, not output statuses.

Custom phone tags: `Voicemail`, `Contacted`, `Correct`, `Wrong Number`, `DNC`. Inactive property statuses and `Dead Number` are not emitted. Mapping validation rejects values outside this vocabulary.

## Multiple labels and events

Known compatible evidence is retained even when another label is unknown. Contradictory property or phone dispositions are reviewed independently. Compatible custom phone tags are combined. Explicit property opt-out retains `dnc`; phone DNC evidence remains restrictive even when correctness is contradictory.

Each run resolves at most one property update per normalized address (phone fallback when address is absent) and one phone update per normalized phone. Latest dated evidence wins, using source times for same-day ties. Undated snapshots cannot be ordered against dated events. Conflicting ties are reviewed rather than resolved by file order. Unknown latest evidence does not restore an older resolved status. Explicit DNC in the submitted run persists across later ordinary activity. This is not an account-wide history lookup; separate runs do not reconcile with one another.

## Import columns and review

- `property_status_updates.csv`: map `status` to Property Status.
- `phone_status_tags_updates.csv`: map `phone_status` to Phone Status and `phone_tag` to custom phone tags. Multiple tags are comma-separated inside a quoted CSV cell. A blank means no additional update, never clear existing tags.
- `marketing_activity_tags.csv`: map `tag` to property tags. Existing tokens remain `(MARKETING) CC - M/YYYY` and `(MARKETING) SMS - M/YYYY`.
- `ingestion_review.csv`: inspect `review_target`, source label/file/row, and reason. This is audit evidence, not an import file.

The preview shows independent property/phone update counts and unresolved labels by target. Downloads contain only resolved statuses; supported outputs can still carry review metadata about another unresolved interpretation. Historical status imports can overwrite current statuses; dated property tags retain activity history. Nothing is imported automatically.
