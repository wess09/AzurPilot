import filecmp
import os
import shutil

from deploy.Windows.config import DeployConfig
from deploy.Windows.logger import Progress, logger


class AppManager(DeployConfig):
    @staticmethod
    def app_asar_replace(
            folder,
            source_paths=(
                './webapp/app.asar',
            ),
            target_path='./toolkit/WebApp/resources/app.asar',
    ):
        """
        Args:
            folder (str): Path to AzurLaneAutoScript
            source_paths (tuple[str]): Candidate source path from git workspace
            target_path (str): Path from AzurLaneAutoScript to app.asar

        Returns:
            bool: If updated.
        """
        source = os.path.abspath(os.path.join(folder, target_path))
        logger.info(f'Old file: {source}')

        update = None
        for rel_path in source_paths:
            candidate = os.path.abspath(os.path.join(folder, rel_path))
            if os.path.isfile(candidate):
                update = candidate
                break
        if update is None:
            logger.info(
                f'No git-built app.asar found in {list(source_paths)}, skip updating'
            )
            return False

        logger.info(f'New file: {update}')

        if os.path.exists(source):
            if filecmp.cmp(source, update, shallow=True):
                logger.info('app.asar is already up to date')
                return False
            else:
                # Keyword "Update app.asar" is used in AlasApp
                # to determine whether there is a hot update
                logger.info(f'Update app.asar {update} -----> {source}')
                os.remove(source)
                shutil.copy(update, source)
                return True
        else:
            logger.info(f'{source} not exists, skip updating')
            return False

    def app_update(self):
        logger.hr(f'Update app', 0)

        if not self.AppAsarUpdate:
            logger.info('AppAsarUpdate is disabled, skip')
            Progress.UpdateAlasApp()
            return False

        self.app_asar_replace(os.getcwd())
        Progress.UpdateAlasApp()
