export function useSearchParams() {
  return new URLSearchParams(window.location.search)
}
