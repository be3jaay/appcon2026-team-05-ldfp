export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000"

export const apiWsBaseUrl = apiBaseUrl.replace(/^http/, "ws")
