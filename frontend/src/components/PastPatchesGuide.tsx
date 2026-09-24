const PastPatchesGuide = () => (
  <section className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 mb-6" aria-labelledby="past-patches-heading">
    <h2 id="past-patches-heading" className="text-base font-bold text-amber-950">Prepare one month for REISift</h2>
    <p className="mt-2 text-sm text-amber-950">Choose the source month → upload calling/SMS files or the three Salesforce reports → review dates and tags → download the import bundle.</p>
    <p className="mt-2 text-xs text-amber-900">Source dates take priority. Undated campaign snapshots use your selected month and are identified in the preview. Review files explain excluded or unresolved rows. After importing tags into REISift, re-export contacts for Gate 2 and the other reports.</p>
  </section>
);
export default PastPatchesGuide;
