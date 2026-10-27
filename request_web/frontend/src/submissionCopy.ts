export function requestSubmissionMessage(lang: "zh" | "en"): string {
  return lang === "zh"
    ? "您的申请已提交，稍后将通过飞书同步申请信息。"
    : "Your request has been submitted. The application details will be shared via Feishu shortly.";
}
