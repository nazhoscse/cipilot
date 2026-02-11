// Utility functions for CI Detector Extension
function parseGitHubRepoInfo() {
    const match = window.location.pathname.match(/^\/(.+?)\/(.+?)(?:\/(tree|blob)\/([^\/]+))?(?:\/|$)/);
    if (!match) return null;
    return {
        owner: match[1],
        repo: match[2],
        branch: match[4] || 'master',
    };
}
window.parseGitHubRepoInfo = parseGitHubRepoInfo;

function isInvalidRepo() {
    const imgs = document.querySelectorAll('img[alt^="404"]');
    return imgs.length > 0;
}
window.isInvalidRepo = isInvalidRepo;
