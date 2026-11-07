import { PageHeader } from "@/components/ui/page-header";
import { DocumentPicker } from "@/components/chat/study-screen";

export default function ChatPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Choose a document"
        description="Open a PDF to ask grounded questions and follow page citations."
      />
      <DocumentPicker />
    </div>
  );
}
