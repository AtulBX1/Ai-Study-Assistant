import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export function ComingSoonPage({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <EmptyState
        title={`${title} is coming soon`}
        description="This part of your study space is being prepared. Your learning materials and progress will appear here in a future step."
      />
    </>
  );
}
