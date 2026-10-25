export function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading court">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {["a", "b", "c", "d", "e"].map((key) => (
          <div key={key} className="h-24 animate-pulse rounded-xl bg-white" />
        ))}
      </div>
      <div className="h-96 animate-pulse rounded-xl bg-white" />
    </div>
  )
}
