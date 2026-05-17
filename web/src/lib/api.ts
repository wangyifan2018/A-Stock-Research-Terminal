const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function getOpenFrApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_OPENFR_API_BASE_URL?.trim();
  return configured || DEFAULT_API_BASE_URL;
}
