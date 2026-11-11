import { apiClient, unwrapApiResult } from "@/lib/api";

export type SyllabusNode = { id?: number; title: string; order: number; keywords?: string[]; sub_topics?: string[]; children: SyllabusNode[] };
export type SyllabusSummary = { id: number; title: string };
export type Coverage = { percent: number; topics: Array<{ topic_id: number; title: string; chunks: number; pages: number[]; documents: number[]; status: string }> };

export async function listSyllabi(): Promise<SyllabusSummary[]> { return unwrapApiResult(await apiClient.GET("/syllabi")) as SyllabusSummary[]; }
export async function getSyllabus(id: number): Promise<{ id: number; title: string; tree: SyllabusNode[] }> { return unwrapApiResult(await apiClient.GET("/syllabi/{syllabus_id}", { params: { path: { syllabus_id: id } } })) as { id: number; title: string; tree: SyllabusNode[] }; }
export async function getCoverage(id: number): Promise<Coverage> { return unwrapApiResult(await apiClient.GET("/syllabi/{syllabus_id}/coverage", { params: { path: { syllabus_id: id } } })) as Coverage; }
export async function previewSyllabus(text: string): Promise<SyllabusNode[]> { const value = unwrapApiResult(await apiClient.POST("/syllabi/preview", { body: { text } })) as { tree: SyllabusNode[] }; return value.tree; }
export async function createSyllabus(input: { title: string; text?: string; document_id?: number }): Promise<{ id: number; title: string; tree: SyllabusNode[] }> { return unwrapApiResult(await apiClient.POST("/syllabi", { body: input })) as { id: number; title: string; tree: SyllabusNode[] }; }
export async function editTopic(syllabusId: number, topicId: number, input: { title?: string; order?: number }) { return unwrapApiResult(await apiClient.PATCH("/syllabi/{syllabus_id}/topics/{topic_id}", { params: { path: { syllabus_id: syllabusId, topic_id: topicId } }, body: input })); }
export async function addTopic(syllabusId: number, title: string, order: number) { return unwrapApiResult(await apiClient.POST("/syllabi/{syllabus_id}/topics", { params: { path: { syllabus_id: syllabusId } }, body: { title, order } })); }
export async function deleteTopic(syllabusId: number, topicId: number) { const result = await apiClient.DELETE("/syllabi/{syllabus_id}/topics/{topic_id}", { params: { path: { syllabus_id: syllabusId, topic_id: topicId } } }); if (!result.response.ok) throw new Error("Could not delete topic."); }
