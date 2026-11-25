"""Runtime update networking; bootstrap deploy modules remain unchanged.

The application downloads Git objects over HTTP/3 first, then lets local Git
inspect or apply them. The original Git transport remains the recovery path
when the configured CDN cannot provide a matching update.
"""

import subprocess

from deploy.api_endpoints import FORCE_UPDATE_CONTROL_URL
from deploy.git import GitManager
from deploy.git_over_cdn.client import (
    CLOUDFLARE_VERSION_KEY_HEADER,
    DEVICE_ID_HEADER,
    GitOverCdnClient,
    _read_device_id,
)
from deploy.git_over_cdn.endpoints import CLOUDFLARE_UPDATE_URLS, FALLBACK_UPDATE_URLS
from deploy.mirrorchyan.client import MirrorChyanClient
from module.base import http
from module.logger import logger


class RuntimeGitOverCdnClient(GitOverCdnClient):
    """Reuse the pack format and Git operations with runtime HTTP networking."""

    @staticmethod
    def _create_session(max_retries=3):
        session = http.Session(download=True, retries=max_retries)
        session.trust_env = False
        device_id = _read_device_id()
        session.headers[DEVICE_ID_HEADER] = device_id
        session.headers[CLOUDFLARE_VERSION_KEY_HEADER] = device_id
        return session

    def close(self):
        session = self.__dict__.pop('session', None)
        if session is not None:
            session.close()

    def fetch(self):
        """Download missing objects and update the remote ref without resetting HEAD."""
        if not self.current_commit or not self.latest_commit:
            return False
        if self.current_commit != self.latest_commit and not self.download_pack():
            return False
        try:
            # Never publish a remote ref to a manifest whose commit is missing.
            self.git_command('cat-file', '-e', f'{self.latest_commit}^{{commit}}')
        except (OSError, subprocess.CalledProcessError) as error:
            self.logger.warning(f'CDN commit is unavailable: {type(error).__name__}')
            return False
        return self.update_refs()


class RuntimeMirrorChyanClient(MirrorChyanClient):
    """Reuse MirrorChyan Git Pack flow with runtime HTTP networking."""

    @staticmethod
    def _create_session(max_retries=2):
        session = http.Session(download=True, retries=max_retries)
        session.trust_env = False
        return session


class RuntimeGitManager(GitManager):
    """Application-only network overrides; deploy never imports this class."""

    @property
    def goc_client(self):
        client = RuntimeGitOverCdnClient(
            url=CLOUDFLARE_UPDATE_URLS,
            fallback_urls=FALLBACK_UPDATE_URLS,
            folder=self.root_filepath,
            source='origin',
            branch=self.Branch,
            git=self.git,
        )
        client.logger = logger
        return client

    @property
    def mirrorchyan_client(self):
        client = RuntimeMirrorChyanClient(
            folder=self.root_filepath,
            cdk=getattr(self, 'MirrorChyanCdk', None) or '',
            source='origin',
            branch=self.Branch,
            git=self.git,
        )
        client.logger = logger
        return client

    @staticmethod
    def cloud_force_update_enabled():
        """Read the update policy through the runtime API transport."""
        try:
            with http.get(FORCE_UPDATE_CONTROL_URL, timeout=5,
                          headers={'User-Agent': http.USER_AGENT}) as response:
                response.raise_for_status()
                try:
                    policy = response.json()
                except ValueError:
                    policy = response.text.strip()
        except http.RequestException as error:
            logger.warning(f'Update policy is unavailable: {type(error).__name__}')
            return None
        if isinstance(policy, dict):
            if policy.get('schema_version') != 2 or not isinstance(policy.get('force_update'), bool):
                logger.warning('Invalid cloud update policy document')
                return None
            policy = policy['force_update']
        if isinstance(policy, bool):
            return policy
        if isinstance(policy, str):
            if policy.lower() in ('true', 'ture'):
                return True
            if policy.lower() in ('false', 'fales'):
                return False
        logger.warning('Invalid cloud update policy document')
        return None

    def fetch_update(self, source='origin', branch=None, max_retry=3, delay=1):
        """Prepare a version check through MirrorChyan or CDN, falling back to Git fetch."""
        branch = branch or self.Branch
        if getattr(self, 'MirrorChyan', False) and source == 'origin' and branch == self.Branch:
            client = self.mirrorchyan_client
            try:
                if client.fetch():
                    self._mirrorchyan_error = ''
                    return
                self._mirrorchyan_error = client.last_error
            finally:
                client.close()
            logger.warning('MirrorChyan fetch failed, falling back to Git')
        if self.GitOverCdn and source == 'origin' and branch == self.Branch:
            client = self.goc_client
            try:
                if client.fetch():
                    return
            finally:
                client.close()
            logger.warning('CDN fetch failed, falling back to Git')
        return self._fetch_with_retry(source, branch, max_retry=max_retry, delay=delay)

    def git_install(self):
        """Apply MirrorChyan or CDN objects, or use the existing repository update fallback."""
        logger.hr('Update AzurPilot', 0)
        if getattr(self, 'MirrorChyan', False):
            client = self.mirrorchyan_client
            try:
                if client.update():
                    self._mirrorchyan_error = ''
                    return
                self._mirrorchyan_error = client.last_error
            finally:
                client.close()
            logger.warning('MirrorChyan update failed, falling back to Git')
        if self.GitOverCdn:
            client = self.goc_client
            try:
                if client.update():
                    return
            finally:
                client.close()
            logger.warning('CDN update failed, falling back to Git')
        self.git_repository_init(repo=self.Repository, source='origin', branch=self.Branch,
                                 proxy=self.GitProxy, ssl_verify=self.SSLVerify)
