"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { listDocuments, readKeyPoints, requestKeyPoints } from "@/lib/documents";
import { downloadStudyExport } from "@/lib/quiz-study";

export default function SummaryPage() {
  const [selected, setSelected] = useState<number | null>(null);
  const [job, setJob] = useState<string | undefined>();
  const [engine, setEngine] = useState("llm");
  const docs = useQuery({ queryKey: ["documents", "summary-picker"], queryFn: () => listDocuments(0, 100) });
  const points = useQuery({ queryKey: ["key-points", selected, job, engine], queryFn: () => readKeyPoints(selected!, job, engine), enabled: selected !== null, refetchInterval: (q) => q.state.data?.status === "queued" || q.state.data?.status === "running" ? 700 : false });
  const start = async (regenerate = false) => { if (selected === null) return; const result = await requestKeyPoints(selected, engine, regenerate); setJob(result.job_id); if (result.status === "complete") await points.refetch(); };
  const result = points.data?.result;
  const exportResult = async (format: "pdf" | "docx") => {
    if (!result?.id) return;
    const blob = await downloadStudyExport("summary", result.id, format);
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `key-points.${format}`; anchor.click(); URL.revokeObjectURL(url);
  };
  return <div className="space-y-6"><PageHeader title="Document summary" description="Grounded crux and key points by chapter or section." />
    <Card><CardContent className="flex flex-wrap items-center gap-3 p-4"><label className="text-sm font-medium" htmlFor="summary-doc">Document</label><select id="summary-doc" className="min-h-10 rounded-md border border-border bg-background px-3" value={selected ?? ""} onChange={e => { setSelected(Number(e.target.value) || null); setJob(undefined); }}><option value="">Choose a document</option>{docs.data?.filter(d => d.status === "ready").map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select><select aria-label="Summary engine" value={engine} onChange={e => setEngine(e.target.value)} className="min-h-10 rounded-md border border-border bg-background px-3"><option value="llm">LLM with fallback</option><option value="extractive">Extractive</option><option value="t5">T5</option></select><Button disabled={selected === null || points.isFetching} onClick={() => void start()}>Generate summary</Button></CardContent></Card>
    {points.data && ["queued", "running"].includes(points.data.status) ? <div><p className="mb-1 text-sm">Generating · {points.data.progress}%</p><progress className="w-full accent-primary" max={100} value={points.data.progress} /></div> : null}
    {points.data?.status === "failed" ? <p role="alert">{points.data.error}</p> : null}
    {result ? <><Card><CardContent className="p-5"><h2 className="text-lg font-semibold">Crux</h2>{result.crux?.map((item, i) => <div key={i} className="mt-2"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{item.text}</ReactMarkdown><Link className="text-primary underline" href={`/chat/${selected}?page=${item.page}`}>p. {item.page}</Link></div>)}<div className="mt-4 flex gap-2"><Button variant="outline" onClick={() => void navigator.clipboard.writeText(result.crux.map(x => x.text).join("\n"))}>Copy crux</Button><Button variant="outline" onClick={() => void exportResult("pdf")}>Export PDF</Button><Button variant="outline" onClick={() => void exportResult("docx")}>Export DOCX</Button><Button variant="outline" onClick={() => void start(true)}>Regenerate</Button></div></CardContent></Card>
      {result.sections?.map((section, i) => <details key={i} className="rounded-lg border border-border p-4" open><summary className="cursor-pointer font-semibold">{section.title} · pp. {section.page_start}–{section.page_end}</summary><ul className="mt-3 space-y-3">{section.items.map((item, j) => <li key={j}><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{item.text}</ReactMarkdown><p className="text-sm text-muted-foreground">{item.kind} · Evidence: {item.evidence_sentence} · <Link className="text-primary underline" href={`/chat/${selected}?page=${item.page}`}>Page {item.page}</Link></p></li>)}</ul></details>)}
      <details className="rounded-lg border border-border p-4"><summary className="cursor-pointer font-medium">Under the hood</summary><p className="mt-2 text-sm text-muted-foreground">Requested: {result.engine_requested}; used: {result.engine_used}{result.fallback_reason ? ` · ${result.fallback_reason}` : ""}. Each item is kept only when its evidence sentence occurs in the cited source page.</p></details></> : null}</div>;
}
