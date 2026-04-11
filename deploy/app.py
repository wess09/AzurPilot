import filecmp
import os
import shutil

from deploy.config import DeployConfig
from deploy.logger import logger
from deploy.utils import *


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
                logger.info(f'Copy {update} -----> {source}')
                os.remove(source)
                shutil.copy(update, source)
                return True
        else:
            logger.info(f'{source} not exists, skip updating')
            return False

    def app_update(self):
        logger.hr(f'Update app.asar', 0)

        # 检查云端更新端点
        cloud_allow = False
        try:
            import requests
            resp = requests.get("https://alas-apiv2.nanoda.work/api/updata", timeout=5)
            if resp.status_code == 200:
                data = resp.text.strip().lower()
                if data == 'true':
                    cloud_allow = True
                elif data == 'false':
                    cloud_allow = False
                else:
                    try:
                        import json
                        res = json.loads(data)
                        if isinstance(res, bool):
                            cloud_allow = res
                    except:
                        pass
        except Exception as e:
            logger.warning(f"Failed to fetch cloud update flag: {e}")
            
        if not cloud_allow:
            logger.info('Cloud update flag is false, skip app update')
            return False

        return self.app_asar_replace(os.getcwd())
