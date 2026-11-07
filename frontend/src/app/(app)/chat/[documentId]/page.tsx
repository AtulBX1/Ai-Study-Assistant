import { StudyScreen } from "@/components/chat/study-screen";

export default async function DocumentChatPage({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  return <StudyScreen documentId={Number(documentId)} />;
}
