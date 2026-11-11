"use client";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
export default function QuizChart({ data }: { data: Array<{ topic: string; accuracy: number }> }) {
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="topic" /><YAxis domain={[0, 100]} unit="%" /><Tooltip formatter={(value) => [`${value}%`, "Accuracy"]} /><Bar dataKey="accuracy" fill="hsl(var(--primary))" /></BarChart></ResponsiveContainer>;
}
