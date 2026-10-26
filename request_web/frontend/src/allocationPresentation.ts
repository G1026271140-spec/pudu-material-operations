type Arrival = {
  required_arrival_time?: string;
  required_arrival_start?: string;
  required_arrival_end?: string;
  requiredArrivalTime?: string;
  requiredArrivalStart?: string;
  requiredArrivalEnd?: string;
};

export function requiredArrivalText(request: Arrival, lang: "zh" | "en"): string {
  const exact = request.required_arrival_time || request.requiredArrivalTime || "";
  if (exact) return exact;
  const start = request.required_arrival_start || request.requiredArrivalStart || "";
  const end = request.required_arrival_end || request.requiredArrivalEnd || "";
  if (start && end && start !== end) return `${start} ${lang === "zh" ? "至" : "to"} ${end}`;
  if (start) return end ? start : `${lang === "zh" ? "最早 " : "From "}${start}`;
  if (end) return `${lang === "zh" ? "最晚 " : "By "}${end}`;
  return lang === "zh" ? "未填写" : "Not provided";
}
