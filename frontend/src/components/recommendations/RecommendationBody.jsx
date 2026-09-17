import {useEffect, useRef, useState} from 'react'
import {
  Alert,
  Spinner,
} from 'react-bootstrap'

import RecommendationRow from './RecommendationRow'

const RECOMMENDATIONS_PER_BATCH = 50

function RecommendationBody({
                              recommendations,
                              loading,
                              onSelectRecommendation,
                            }) {
  const [visibleCount, setVisibleCount] = useState(
    RECOMMENDATIONS_PER_BATCH
  )

  const scrollRef = useRef(null)
  const loadMoreRef = useRef(null)

  const visibleRecommendations =
    recommendations.slice(
      0,
      visibleCount
    )

  useEffect(() => {
    setVisibleCount(
      Math.min(
        RECOMMENDATIONS_PER_BATCH,
        recommendations.length
      )
    )
  }, [recommendations.length])

  useEffect(() => {
    const scrollContainer = scrollRef.current
    const target = loadMoreRef.current

    if (!scrollContainer || !target) {
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting) {
          return
        }

        setVisibleCount((current) =>
          Math.min(
            current +
            RECOMMENDATIONS_PER_BATCH,
            recommendations.length
          )
        )
      },
      {
        root: scrollContainer,
        rootMargin: '500px',
      }
    )

    observer.observe(target)

    return () => {
      observer.disconnect()
    }
  }, [
    recommendations.length,
    visibleCount,
  ])

  if (loading) {
    return (
      <div className="d-flex flex-column align-items-center justify-content-center flex-grow-1 py-5">
        <Spinner animation="border"/>
        <div className="mt-3 text-muted">
          Generating recommendations...
        </div>
      </div>
    )
  }

  if (recommendations.length === 0) {
    return (
      <div className="flex-grow-1 d-flex flex-column">
        <Alert variant="secondary" className="mb-0">
          No recommendations yet. Open Settings and run the recommender.
        </Alert>
      </div>
    )
  }

  const hasMore =
    visibleCount <
    recommendations.length

  // Width for the 10 remaining columns matching the row layout (2/3 spread across 10 columns)
  const remainingColumnWidth = `${(2 / 3) / 10 * 100}%`

  return (
    <div
      ref={scrollRef}
      className="recommendation-scroll flex-grow-1 overflow-y-auto overflow-x-auto position-relative"
    >
      {/* table-responsive wrapper handles smooth horizontal scrolling when zoomed in */}
      <div className="table-responsive w-100">
        <table className="table table-hover align-middle mb-0" style={{minWidth: '850px'}}>
          <thead className="sticky-top bg-body">
          <tr>
            <th className="text-center" style={{width: '33.33%'}}>Artist - Title</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>PP</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>Mods</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>Stars</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>BPM</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>CS</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>AR</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>OD</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>Length</th>
            <th className="text-center" style={{width: remainingColumnWidth}}>Combo</th>
          </tr>
          </thead>

          <tbody>
          {visibleRecommendations.map(
            (recommendation, index) => (
              <RecommendationRow
                key={
                  recommendation.variant_id ??
                  recommendation.beatmap_id ??
                  index
                }
                recommendation={
                  recommendation
                }
                onSelectRecommendation={onSelectRecommendation}
              />
            )
          )}
          </tbody>
        </table>
      </div>

      {hasMore && (
        <div
          ref={loadMoreRef}
          className="text-center py-4"
        >
          <Spinner
            animation="border"
            size="sm"
          />
          <div className="mt-2 text-muted small">
            Loading more recommendations...
          </div>
        </div>
      )}

      {!hasMore && (
        <div className="text-center text-muted py-4 small">
          Showing all{' '}
          {recommendations.length}{' '}
          recommendations.
        </div>
      )}
    </div>
  )
}

export default RecommendationBody