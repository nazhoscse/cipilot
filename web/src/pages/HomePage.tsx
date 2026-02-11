import { useCallback, useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { RotateCcw } from 'lucide-react'
import { RepoInput, ConversionPanel } from '../components/migration'
import { Button } from '../components/common'
import { useMigration } from '../context/MigrationContext'
import { useSettings } from '../context/SettingsContext'
import { useToast } from '../context/ToastContext'
import type { Repository } from '../types/api'
import type { DetectedService, MigrationHistoryItem } from '../types/migration'

// Known CI/CD config file paths - matches Chrome extension's keyCIConfigs
const CI_CONFIG_PATHS: Record<string, { paths: string[]; name: string; isFolder?: boolean }> = {
  github: { paths: ['.github/workflows'], name: 'GitHub Actions', isFolder: true },
  travis: { paths: ['.travis.yml'], name: 'Travis CI' },
  circle: { paths: ['.circleci'], name: 'CircleCI', isFolder: true },
  appveyor: { paths: ['appveyor.yml', '.appveyor.yml'], name: 'AppVeyor' },
  gitlab: { paths: ['.gitlab-ci.yml'], name: 'GitLab CI' },
  semaphore: { paths: ['.semaphore', '.semaphore/semaphore.yml'], name: 'Semaphore', isFolder: true },
  buildkite: { paths: ['.buildkite'], name: 'Buildkite', isFolder: true },
  azure: { paths: ['azure-pipelines.yml', '.azure-pipelines.yml'], name: 'Azure Pipelines' },
  bitbucket: { paths: ['bitbucket-pipelines.yml'], name: 'Bitbucket Pipelines' },
  cirrus: { paths: ['.cirrus.yml'], name: 'Cirrus CI' },
  scrutinizer: { paths: ['.scrutinizer.yml'], name: 'Scrutinizer CI' },
  codeship: { paths: ['codeship-services.yml'], name: 'Codeship' },
  wercker: { paths: ['wercker.yml'], name: 'Wercker' },
  bitrise: { paths: ['bitrise.yml'], name: 'Bitrise' },
  bamboo: { paths: ['bamboo.yml'], name: 'Bamboo' },
  gocd: { paths: ['.gocd.yaml'], name: 'GoCD' },
  codemagic: { paths: ['codemagic.yaml'], name: 'Codemagic' },
  jenkins: { paths: ['Jenkinsfile'], name: 'Jenkins' },
  drone: { paths: ['.drone.yml'], name: 'Drone CI' },
}

export function HomePage() {
  const {
    state,
    setRepository,
    setDetectedServices,
    setFetchedConfigs,
    setConversionResult,
    setStep,
    setLoading,
    setError,
    reset,
  } = useMigration()
  const { settings } = useSettings()
  const toast = useToast()
  const location = useLocation()
  const [detectError, setDetectError] = useState<string | undefined>()

  // Check for migration data from history (continue editing)
  // Runs on mount and whenever location changes (to catch navigation from sidebar)
  useEffect(() => {
    const editData = sessionStorage.getItem('cigrate-edit-migration')
    if (editData) {
      try {
        const historyItem: MigrationHistoryItem = JSON.parse(editData)
        sessionStorage.removeItem('cigrate-edit-migration')

        // Reset current state first
        reset()

        // Set repository
        setRepository(historyItem.repository)

        // Use detectedServices if available (new format), otherwise fall back to sourceServices (old format)
        const detectedServices: DetectedService[] = historyItem.detectedServices || 
          historyItem.sourceServices.map((service) => ({
            name: service,
            path: getConfigPath(service),
            url: `${historyItem.repository.url}/blob/${historyItem.repository.branch}/${getConfigPath(service)}`,
          }))
        setDetectedServices(detectedServices)

        // Set fetched configs (original configs)
        setFetchedConfigs(historyItem.originalConfigs)

        // Set conversion result
        setConversionResult({
          convertedConfig: historyItem.convertedConfig,
          validation: historyItem.validation,
          attempts: historyItem.attempts,
        })

        // Set step to review so user can edit
        setStep('review')

        toast.info('Continue editing', `Loaded migration for ${historyItem.repository.owner}/${historyItem.repository.name}`)
      } catch (error) {
        console.error('Failed to load migration from history:', error)
        toast.error('Load failed', 'Could not load migration data from history')
      }
    }
  }, [location, reset, setRepository, setDetectedServices, setFetchedConfigs, setConversionResult, setStep, toast])

  const detectCIServices = useCallback(
    async (repo: Repository) => {
      reset()
      setDetectError(undefined)
      setLoading(true)
      setStep('detecting')

      try {
        // First, fetch the repository info to get the actual default branch
        const repoInfoResponse = await fetch(
          `https://api.github.com/repos/${repo.owner}/${repo.name}`,
          {
            headers: settings.githubToken 
              ? { Authorization: `Bearer ${settings.githubToken}` }
              : {}
          }
        )

        let actualBranch = repo.branch
        if (repoInfoResponse.ok) {
          const repoInfo = await repoInfoResponse.json()
          actualBranch = repoInfo.default_branch || repo.branch
        }

        const repoWithUrl = {
          owner: repo.owner,
          name: repo.name,
          branch: actualBranch,
          url: `https://github.com/${repo.owner}/${repo.name}`,
        }
        setRepository(repoWithUrl)

        const detectedServices: DetectedService[] = []
        const fetchedConfigs: Record<string, string> = {}

        // Try to detect each CI service
        for (const [_key, config] of Object.entries(CI_CONFIG_PATHS)) {
          // Skip if already detected this service
          if (detectedServices.find((s) => s.name === config.name)) continue

          for (const path of config.paths) {
            try {
              // Check if it's a folder-based CI config
              if (config.isFolder) {
                // List directory contents
                const contents = await fetchGitHubContents(
                  repo.owner,
                  repo.name,
                  path,
                  settings.githubToken
                )

                if (Array.isArray(contents) && contents.length > 0) {
                  // Found the folder - add service
                  detectedServices.push({
                    name: config.name,
                    path,
                    url: `https://github.com/${repoWithUrl.owner}/${repoWithUrl.name}/tree/${repoWithUrl.branch}/${path}`,
                  })

                  // Fetch each config file in the folder
                  for (const file of contents) {
                    if (file.type === 'file' && (file.name.endsWith('.yml') || file.name.endsWith('.yaml'))) {
                      const fileContent = await fetchGitHubFile(
                        repo.owner,
                        repo.name,
                        file.path,
                        settings.githubToken
                      )
                      if (fileContent) {
                        fetchedConfigs[`${config.name}:${file.name}`] = fileContent
                      }
                    }
                  }
                  break // Found this service, move to next
                }
              } else {
                // Single file check
                const content = await fetchGitHubFile(
                  repo.owner,
                  repo.name,
                  path,
                  settings.githubToken
                )

                if (content) {
                  detectedServices.push({
                    name: config.name,
                    path,
                    url: `https://github.com/${repoWithUrl.owner}/${repoWithUrl.name}/blob/${repoWithUrl.branch}/${path}`,
                  })
                  fetchedConfigs[config.name] = content
                  break // Found this service, move to next
                }
              }
            } catch {
              // File/directory doesn't exist, continue
            }
          }
        }

        if (detectedServices.length === 0) {
          setDetectError('No CI/CD configurations found in this repository')
          setStep('input')
          toast.warning('No CI/CD found', 'This repository does not appear to have CI/CD configurations')
        } else {
          setDetectedServices(detectedServices)
          setFetchedConfigs(fetchedConfigs)
          setStep('review')
          toast.success(
            'CI/CD detected',
            `Found ${detectedServices.length} service${detectedServices.length > 1 ? 's' : ''}`
          )
        }
      } catch (error) {
        if (error instanceof Error && error.message === 'RATE_LIMIT_EXCEEDED') {
          const message = 'GitHub API rate limit exceeded. Please add your GitHub Personal Access Token in Settings to continue browsing repositories.'
          setDetectError(message)
          setError(message)
          setStep('input')
          toast.error('Rate Limit Exceeded', message)
        } else {
          const message = error instanceof Error ? error.message : 'Failed to detect CI services'
          setDetectError(message)
          setError(message)
          setStep('input')
          toast.error('Detection failed', message)
        }
      } finally {
        setLoading(false)
      }
    },
    [
      reset,
      setRepository,
      setDetectedServices,
      setFetchedConfigs,
      setStep,
      setLoading,
      setError,
      settings.githubToken,
      toast,
    ]
  )

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Hero Section */}
      <div className="text-center mb-8">
        <h1 className="text-3xl sm:text-4xl font-bold text-[var(--text-primary)] mb-3">
          Migrate CI/CD Configuration
        </h1>
        <p className="text-lg text-[var(--text-secondary)] max-w-2xl mx-auto">
          Convert your CI/CD configurations to GitHub Actions using AI
        </p>
        {/* Start New button - shown when there's an active migration */}
        {(state.repository || state.detectedServices.length > 0 || state.conversionResult) && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              reset()
              toast.info('Session cleared', 'Ready to start a new migration')
            }}
            className="mt-4"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            Start New Migration
          </Button>
        )}
      </div>

      {/* Repository Input */}
      <RepoInput
        onSubmit={detectCIServices}
        isLoading={state.isLoading && state.step === 'detecting'}
        error={detectError}
        initialRepo={state.repository}
      />

      {/* Conversion Panel */}
      {(state.detectedServices.length > 0 || state.conversionResult) && (
        <ConversionPanel />
      )}
    </div>
  )
}

// Helper functions to fetch from GitHub
async function fetchGitHubFile(
  owner: string,
  repo: string,
  path: string,
  token?: string
): Promise<string | null> {
  try {
    const headers: Record<string, string> = {
      Accept: 'application/vnd.github.v3.raw',
    }
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }

    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/contents/${path}`,
      { headers }
    )

    if (!response.ok) {
      // Check for rate limit error
      if (response.status === 403) {
        const errorData = await response.json().catch(() => ({}))
        if (errorData.message?.includes('API rate limit exceeded')) {
          throw new Error('RATE_LIMIT_EXCEEDED')
        }
      }
      return null
    }

    return await response.text()
  } catch (error) {
    if (error instanceof Error && error.message === 'RATE_LIMIT_EXCEEDED') {
      throw error
    }
    return null
  }
}

async function fetchGitHubContents(
  owner: string,
  repo: string,
  path: string,
  token?: string
): Promise<Array<{ name: string; path: string; type: string }>> {
  try {
    const headers: Record<string, string> = {
      Accept: 'application/vnd.github.v3+json',
    }
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }

    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/contents/${path}`,
      { headers }
    )

    if (!response.ok) {
      // Check for rate limit error
      if (response.status === 403) {
        const errorData = await response.json().catch(() => ({}))
        if (errorData.message?.includes('API rate limit exceeded')) {
          throw new Error('RATE_LIMIT_EXCEEDED')
        }
      }
      return []
    }

    return await response.json()
  } catch (error) {
    if (error instanceof Error && error.message === 'RATE_LIMIT_EXCEEDED') {
      throw error
    }
    return []
  }
}

// Helper to get config file path for a service name
function getConfigPath(service: string): string {
  const paths: Record<string, string> = {
    'GitHub Actions': '.github/workflows',
    'Travis CI': '.travis.yml',
    'CircleCI': '.circleci',
    'AppVeyor': 'appveyor.yml',
    'GitLab CI': '.gitlab-ci.yml',
    'Semaphore': '.semaphore',
    'Buildkite': '.buildkite',
    'Azure Pipelines': 'azure-pipelines.yml',
    'Bitbucket Pipelines': 'bitbucket-pipelines.yml',
    'Cirrus CI': '.cirrus.yml',
    'Scrutinizer CI': '.scrutinizer.yml',
    'Codeship': 'codeship-services.yml',
    'Wercker': 'wercker.yml',
    'Bitrise': 'bitrise.yml',
    'Bamboo': 'bamboo.yml',
    'GoCD': '.gocd.yaml',
    'Codemagic': 'codemagic.yaml',
    'Jenkins': 'Jenkinsfile',
    'Drone CI': '.drone.yml',
  }
  return paths[service] || 'config.yml'
}
