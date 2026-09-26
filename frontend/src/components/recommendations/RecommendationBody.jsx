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
  const [visibleCount, setVisibleCount] = useState(RECOMMENDATIONS_PER_BATCH)

  const [audioVolume, setAudioVolume] = useState(0.01)

  const scrollRef = useRef(null)
  const loadMoreRef = useRef(null)

  const visibleRecommendations = recommendations.slice(0, visibleCount)

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
      <div
        className="d-flex flex-column align-items-center justify-content-center flex-grow-1"
        style={{minHeight: 0}}
      >
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
          No recommendations yet. Apply some settings and run the recommender.
        </Alert>
      </div>
    )
  }

  const hasMore = visibleCount < recommendations.length

  return (
    <div
      ref={scrollRef}
      className="recommendation-scroll flex-grow-1 overflow-auto position-relative"
      style={{minHeight: 0}}
    >
      {/* table-responsive wrapper handles smooth horizontal scrolling when zoomed in */}
      <div className="w-100">
        <table
          className="table table-hover table-sm align-middle mb-0"
          style={{
            minWidth: '850px',
            width: '100%',
          }}
        >
          <thead className="sticky-top bg-body">
          <tr>
            <th className="text-center">Artist - Title</th>
            <th className="text-center">PP</th>
            <th className="text-center">Mods</th>
            <th className="text-center">Stars</th>
            <th className="text-center">BPM</th>
            <th className="text-center">CS</th>
            <th className="text-center">AR</th>
            <th className="text-center">OD</th>
            <th className="text-center">Length</th>
            <th className="text-center">Combo</th>
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
                audioVolume={audioVolume}
                setAudioVolume={setAudioVolume}
              />
            )
          )}
          </tbody>
        </table>
      </div>

      {hasMore && (
        <div
          ref={loadMoreRef}
          className="text-center py-3"
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
        <div className="text-center text-muted py-3 small">
          Showing all{' '}
          {recommendations.length}{' '}
          recommendations.
        </div>
      )}
    </div>
  )
}

export default RecommendationBody