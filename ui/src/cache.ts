import axios from 'axios'
import type { QueryClient } from '@tanstack/react-query'

/**
 * Clear server-side TTL cache + invalidate all React Query cached data.
 * Call after any write operation so records, stats, and agent data all refresh.
 */
export async function invalidateAll(queryClient: QueryClient) {
  await axios.post('/api/cache/clear').catch(() => {})
  await queryClient.invalidateQueries()
}
