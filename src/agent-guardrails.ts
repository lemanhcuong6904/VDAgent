const ENGLISH_GREETING = /^(hi|hello|hey|good morning|good afternoon|good evening)[!.?,\s]*$/i;
const VIETNAMESE_GREETING = /^(xin chào|chào(?: bạn)?|chào buổi sáng|chào buổi tối)[!.?,\s]*$/i;

export function greetingReply(input: string): string | null {
  const value = input.trim();
  if (VIETNAMESE_GREETING.test(value)) return "Chào bạn! Mình có thể giúp gì?";
  if (ENGLISH_GREETING.test(value)) return "Hello! How can I help?";
  return null;
}
