from typing import Dict, Optional, Set

from aiohttp import web

from mapadroid.db.helper import SettingsRoutecalcHelper
from mapadroid.db.model import Base, SettingsArea, SettingsRoutecalc
from mapadroid.db.resource_definitions.AreaIdle import AreaIdle
from mapadroid.db.resource_definitions.AreaIvMitm import AreaIvMitm
from mapadroid.db.resource_definitions.AreaMonMitm import AreaMonMitm
from mapadroid.db.resource_definitions.AreaPokestops import AreaPokestops
from mapadroid.db.resource_definitions.AreaRaidsMitm import AreaRaidsMitm
from mapadroid.madmin.endpoints.api.resources.AbstractResourceEndpoint import \
    AbstractResourceEndpoint
from mapadroid.worker.WorkerType import WorkerType


class AreaEndpoint(AbstractResourceEndpoint):
    async def _create_instance(self, identifier) -> Base:
        api_request_data = await self.request.json()
        mode: WorkerType = WorkerType(api_request_data.get("mode", None))
        area = self._get_db_wrapper().create_area_instance(mode)
        area.mode = mode.value
        area.instance_id = self._get_instance_id()
        area.area_id = identifier
        return area

    async def _fetch_all_from_db(self, **kwargs) -> Dict[int, Base]:
        return await self._get_db_wrapper().get_all_areas(self._session)

    def _resource_info(self, db_entry: Optional[SettingsArea] = None) -> Dict:
        if not db_entry:
            return {}
        elif db_entry.mode == WorkerType.IDLE.value:
            return AreaIdle.configuration
        elif db_entry.mode == WorkerType.IV_MITM.value:
            return AreaIvMitm.configuration
        elif db_entry.mode == WorkerType.MON_MITM.value:
            return AreaMonMitm.configuration
        elif db_entry.mode == WorkerType.STOPS.value:
            return AreaPokestops.configuration
        elif db_entry.mode == WorkerType.RAID_MITM.value:
            return AreaRaidsMitm.configuration
        else:
            return {}

    def _attributes_to_ignore(self) -> Set[str]:
        return {"area_id", "mode", "guid"}

    async def _fetch_from_db(self, identifier, **kwargs) -> Optional[Base]:
        return await self._get_db_wrapper().get_area(self._session, identifier)

    # TODO: '%s/<string:identifier>' optionally at the end of the route
    # TODO: ResourceEndpoint class that loads the mode accordingly before patch/post etc are called (populate_mode)

    async def post(self) -> web.Response:
        identifier = self.request.match_info.get('identifier', None)
        api_request_data = await self.request.json()
        if self.request.content_type == 'application/json-rpc':
            if not identifier:
                return self._json_response(self.request.method, status=405)
            try:
                call = api_request_data['call']
                # args = api_request_data.get('args', {})
                if call == 'recalculate':
                    return await self._recalc_area(identifier)
                else:
                    # RPC not implemented
                    return self._json_response(call, status=501)
            except KeyError:
                return self._json_response("Invalid key found in request.", status=501)
        else:
            return await super().post()

    async def _recalc_area(self, identifier):
        area: Optional[SettingsArea] = await self._get_db_wrapper().get_area(self._session, identifier)
        if not area:
            return self._json_response(text="Unable to recalc, area not found", status=422)
        routecalc_id: Optional[int] = getattr(area, "routecalc", None)
        # iv_mitm is PrioQ driven and idle does not have a route.  This are not recalcable and the returned
        # status should be representative of that
        if area.mode in ['iv_mitm', 'idle']:
            return self._json_response(text='Unable to recalc mode %s' % (area.mode,), status=422)
        routecalc: Optional[SettingsRoutecalc] = None
        if routecalc_id:
            routecalc: Optional[SettingsRoutecalc] = await SettingsRoutecalcHelper \
                .get(self._session, routecalc_id)
        if routecalc and routecalc.recalc_status == 0:
            # Start the recalculation.  This can take a little bit if the routemanager needs to be started
            status = self._get_mapping_manager().routemanager_recalcualte(area.area_id)
            if status:
                return self._json_response(status=204)
            else:
                # Unable to turn on the routemanager.  Probably should use another error code
                return self._json_response(status=409)
        else:
            # Do not allow another recalculation if one is already running.  This value is reset on startup
            # so it will not be stuck in this state
            return self._json_response(text='Recalc is already running on this Area', status=422)
