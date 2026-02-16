import { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { OnboardingGuide } from './components/common'
import { HomePage } from './pages/HomePage'
import { HistoryPage } from './pages/HistoryPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { useSettings } from './context/SettingsContext'
import { initAnalyticsSession } from './utils/analytics'

// Get API base URL for analytics
const getApiBaseUrl = (): string => {
  if (import.meta.env.DEV) {
    return '' // Use proxy in dev
  }
  return import.meta.env.VITE_API_URL || ''
}

function App() {
  const { showOnboarding, setOnboardingComplete, onboardingStartStep } = useSettings()

  // Initialize analytics session on app load
  useEffect(() => {
    const apiBaseUrl = getApiBaseUrl()
    initAnalyticsSession(apiBaseUrl).catch(() => {
      // Analytics errors should never break the app
    })
  }, [])

  const handleOnboardingComplete = () => {
    setOnboardingComplete(true)
  }

  const handleOnboardingSkip = () => {
    setOnboardingComplete(true)
  }

  return (
    <>
      <OnboardingGuide
        isOpen={showOnboarding}
        onComplete={handleOnboardingComplete}
        onSkip={handleOnboardingSkip}
        startStep={onboardingStartStep}
      />
      <AppLayout>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </AppLayout>
    </>
  )
}

export default App
