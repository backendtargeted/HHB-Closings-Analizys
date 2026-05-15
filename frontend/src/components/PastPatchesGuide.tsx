/**
 * Plain-language guide for the Past patches REISift tag generator.
 * Pairs with RUNBOOK.md for operators patching CRM-driven tags into REISift.
 */
const PastPatchesGuide = () => {
  return (
    <section
      className="rounded-2xl border border-amber-200/90 bg-gradient-to-br from-amber-50/90 to-orange-50/40 px-5 py-5 mb-6 shadow-sm"
      aria-labelledby="past-patches-heading"
    >
      <h2 id="past-patches-heading" className="text-base font-bold text-amber-950">
        What you are doing here
      </h2>
      <p className="text-sm text-amber-950/85 mt-2 leading-relaxed">
        <strong>Goal:</strong> turn raw marketing + CRM extracts into the four CSV files REISift expects
        for property status, phone status/tags, Salesforce-style tag rows, and closings month markers{' '}
        <code className="text-xs bg-white/70 px-1.5 py-0.5 rounded border border-amber-200/80">
          (CLOSED) 8020 - M/YYYY
        </code>
        . After you import those into REISift and re-export contacts, use{' '}
        <strong>Regular updates</strong> for normal closings-vs-tags analysis.
      </p>
      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-amber-950/90">
        <div className="rounded-lg border border-amber-200/70 bg-white/60 p-3">
          <p className="font-semibold text-amber-950 mb-1">Inputs (4)</p>
          <ul className="list-disc list-inside space-y-1">
            <li>Cold calling CSV (Log Type + Phone + Address…)</li>
            <li>SMS folder as many CSVs (status from each filename)</li>
            <li>CRM updates CSV (leadstatus + dates when present)</li>
            <li>Closings workbook (.xlsx) with Date Closed + Address</li>
          </ul>
        </div>
        <div className="rounded-lg border border-amber-200/70 bg-white/60 p-3">
          <p className="font-semibold text-amber-950 mb-1">Outputs (REISift)</p>
          <ul className="list-disc list-inside space-y-1 font-mono text-[11px]">
            <li>property_status_updates.csv</li>
            <li>phone_status_tags_updates.csv</li>
            <li>salesforce_status_tags.csv</li>
            <li>closings_status_tags.csv</li>
          </ul>
        </div>
      </div>
      <p className="text-xs text-amber-900/70 mt-4 border-t border-amber-200/60 pt-3">
        <strong>Analysis link:</strong> the <code className="font-mono">salesforce_status_tags.csv</code> file produces{' '}
        <code className="font-mono">(SF) UPDATED …</code> / <code className="font-mono">(SF) STATUS …</code> rows in REISift.
        After bulk import and re-export, <strong>Regular updates</strong> uses those tags in the{' '}
        <strong>Lead lifecycle</strong> funnel and path views (along with list/skip/8020 markers). Duplicate identical tags on one row are counted once in reports.
      </p>
      <p className="text-xs text-amber-900/70">
        Operator checklist: <code className="font-mono">RUNBOOK.md</code>. Report rules: <code className="font-mono">docs/REPORT_METHODOLOGY.md</code>.
        One-time Podio backfills: <code className="font-mono">scripts/one_time_podio_closings_opps_tags_bundle.py</code> (see RUNBOOK playbook A).
      </p>
    </section>
  );
};

export default PastPatchesGuide;
