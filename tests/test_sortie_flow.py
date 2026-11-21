"""实机界面与内存状态机回放，不连接模拟器或写入用户配置。"""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import pytest

import module.config.server as server

server.server = 'cn'

from module.campaign.multiple_sorties import (
    OCR_MULTIPLE_COUNT, OCR_MULTIPLE_OIL,
    MultipleSorties, multiple_sorties_count,
)
from module.combat.auto_search_combat import AutoSearchCombat
from module.exception import CampaignEnd
from module.handover.handover import HandoverDuration, OperationHandover
from module.map.assets import (
    HANDOVER_BOOK_ITEM, HANDOVER_CHECK, HANDOVER_CONFLICT_CHECK, HANDOVER_DIALOG_CLOSE,
    HANDOVER_EXCHANGE_CHECK, HANDOVER_EXCHANGE_TIME, HANDOVER_PASS_CLICK,
    HANDOVER_START_CLICK, HANDOVER_TAB, HANDOVER_TAB_UNSUPPORTED,
    MULTIPLE_SORTIES_CHECK, MULTIPLE_SORTIES_ENTER,
    MULTIPLE_SORTIES_RESULT_CHECK,
)
from module.map.map_operation import MapOperation
from module.ocr.models import OCR_MODEL
from module.retire.retirement import Retirement


FIXTURES = Path(__file__).parent / 'fixtures' / 'sortie_flow'


def screenshot(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / f'{name}.png')), cv2.COLOR_BGR2RGB)


@pytest.mark.parametrize('name,expected', [
    ('multiple_once', MULTIPLE_SORTIES_CHECK),
    ('multiple_result', MULTIPLE_SORTIES_RESULT_CHECK),
    ('handover_completed', HANDOVER_PASS_CLICK),
    ('handover_conflict', HANDOVER_CONFLICT_CHECK),
    ('handover_reward', None),
])
def test_real_screens_distinguish_handover_and_multiple_results(name, expected):
    image = screenshot(name)
    checks = [MULTIPLE_SORTIES_CHECK, MULTIPLE_SORTIES_RESULT_CHECK,
              HANDOVER_PASS_CLICK, HANDOVER_CONFLICT_CHECK]
    assert [button for button in checks if button.match(image, offset=(20, 20))] == (
        [expected] if expected is not None else [])


def test_entry_and_help_are_recognized_on_real_screens():
    assert MULTIPLE_SORTIES_ENTER.match(screenshot('multiple_entry'), offset=(20, 20))
    context = object.__new__(OperationHandover)
    context.config = SimpleNamespace(BUTTON_OFFSET=(20, 20))
    context.device = SimpleNamespace(image=screenshot('handover_help'), stuck_record_add=Mock())
    context.interval_timer = {}
    context.appear_then_click = Mock(return_value=True)
    assert context.handle_handover_help()
    context.device.image = screenshot('handover_conflict')
    assert not context.handle_handover_help()


@pytest.mark.parametrize('name,count,cost', [('multiple_once', 1, 167), ('multiple_ten', 10, 1670)])
def test_real_numeric_ocr_does_not_include_chinese_unit(name, count, cost):
    with patch('module.ocr.ocr.OCR_MODEL', OCR_MODEL):
        image = screenshot(name)
        assert OCR_MULTIPLE_COUNT.ocr(image) == count
        assert OCR_MULTIPLE_COUNT.last_valid
        assert OCR_MULTIPLE_OIL.ocr(image) == cost
        assert OCR_MULTIPLE_OIL.last_valid


def test_batch_respects_remaining_runs_and_single_stage_constraints():
    config = SimpleNamespace(Campaign_MultipleSortiesCount=10, StopCondition_MapAchievement='non_stop')
    assert multiple_sorties_count(config, remaining=2) == 2
    assert multiple_sorties_count(config, total_remaining=1) == 1
    assert multiple_sorties_count(config, one_time=True) == 1
    config.StopCondition_MapAchievement = 'map_3_stars'
    assert multiple_sorties_count(config) == 1
    config.Campaign_MultipleSortiesCount = 0
    assert multiple_sorties_count(config) == 0


def test_final_handover_may_exceed_daily_budget():
    deficit = OperationHandover.handover_time_deficit
    assert deficit(timedelta(seconds=77 * 375), timedelta(hours=8), 375) == timedelta()
    assert deficit(timedelta(seconds=77), timedelta(seconds=1), 1) == timedelta()
    assert deficit(timedelta(seconds=77), timedelta(), 1) == timedelta(seconds=1)
    assert deficit(timedelta(seconds=154), timedelta(seconds=77), 2) == timedelta(seconds=1)


def test_handover_duration_distinguishes_empty_text_and_zero_budget():
    reader = HandoverDuration((0, 0, 1, 1))
    assert reader.after_process('00:00:00') == '00:00:00'
    assert reader.last_valid
    reader.after_process('')
    assert not reader.last_valid


def test_handover_count_is_clamped_without_unreachable_plus_clicks():
    context = SimpleNamespace(handover_count_max=Mock(return_value=375),
                              handover_input_count=Mock(return_value=True))
    assert OperationHandover.handover_set_count(context, 999)
    context.handover_input_count.assert_called_once_with(375)


def test_missing_book_button_is_retryable_instead_of_empty_inventory():
    context = SimpleNamespace(handover_count_max=lambda: 375,
                              handover_click_until_stable=lambda *args: -1)
    assert OperationHandover.handover_consume_all_book(context) == -1


@pytest.mark.parametrize('completed,supported,expected', [
    (1, True, True), (0, True, True), (0, False, False), (1, False, False),
])
def test_unlock_attempts_exactly_one_continuous_sortie(completed, supported, expected):
    campaign = SimpleNamespace(config=SimpleNamespace(MAP_IS_ONE_TIME_STAGE=False),
                               run_multiple_sorties=Mock(return_value=completed))
    context = SimpleNamespace(campaign=campaign, config=SimpleNamespace(OperationHandover_OilLimit=1000),
                              handover_enter=Mock(),
                              handover_check_support=Mock(return_value=supported))
    assert OperationHandover.handover_unlock(context) is expected
    campaign.run_multiple_sorties.assert_called_once_with(1, oil_limit=1000)
    context.handover_enter.assert_called_once_with()


@pytest.mark.parametrize('task', ['Main', 'Event'])
def test_completed_handover_is_claimed_before_main_or_event_continues(task):
    context = SimpleNamespace(
        config=SimpleNamespace(task=SimpleNamespace(command=task), cross_set=Mock()), device=Mock(),
        handover_conflict_appear=lambda: True,
        appear=lambda button, **kwargs: button is HANDOVER_PASS_CLICK,
    )
    with patch.object(OperationHandover, 'handover_reward', return_value=True) as claim:
        assert MapOperation.handle_handover_conflict(context)
    claim.assert_called_once_with()
    context.config.cross_set.assert_called_once()


def test_other_stage_prompt_opens_real_details():
    context = SimpleNamespace(
        handover_conflict_appear=lambda: True,
        appear=lambda button, **kwargs: button is HANDOVER_CONFLICT_CHECK,
        appear_then_click=Mock(return_value=True),
    )
    assert MapOperation.handle_handover_conflict(context)
    context.appear_then_click.assert_called_once_with(HANDOVER_CHECK, offset=(20, 20), interval=2)


def test_next_week_trigger_is_never_used_as_commission_end():
    now = datetime(2026, 11, 16, 12)
    config = SimpleNamespace(
        cross_get=lambda keys, default=None: now + timedelta(days=7) if keys[-1] == 'NextRun' else None,
        task_delay=Mock(), is_task_enabled=lambda task: False,
    )
    with patch('module.map.map_operation.current_time', return_value=now):
        target = MapOperation.handover_conflict_delay(SimpleNamespace(config=config))
    assert target == now + timedelta(minutes=15)


def test_start_requires_a_positive_commission_detail_after_click():
    state = {'page': 'panel', 'time': 100, 'start_clicks': 0}
    entrance = object()

    def shot():
        state['time'] += 1

    def click(button, **kwargs):
        if button is HANDOVER_START_CLICK and state['page'] == 'panel':
            state['start_clicks'] += 1
            state['page'] = 'chapter'
            return True
        if button is HANDOVER_DIALOG_CLOSE and state['page'] == 'detail':
            state['page'] = 'chapter'
            return True
        return False

    def enter(*args, **kwargs):
        state['page'] = 'detail'
        return True

    context = SimpleNamespace(
        device=SimpleNamespace(screenshot=shot), handle_popup_confirm=lambda *args: False,
        handover_panel_appear=lambda: state['page'] == 'panel',
        handover_dialog_appear=lambda: state['page'] == 'detail', appear_then_click=click,
        campaign=SimpleNamespace(ENTRANCE=entrance, appear=lambda *args: state['page'] == 'chapter',
                                 appear_then_click=enter),
    )
    with patch('module.base.timer.time', side_effect=lambda: state['time']):
        assert OperationHandover.handover_start(context)
        assert state['start_clicks'] == 1
        state['page'] = 'missing'
        state['start_clicks'] = 0
        assert not OperationHandover.handover_start(context)
        assert state['start_clicks'] == 0


def test_exchange_waits_for_real_quota_increase_after_confirmation_cooldown():
    state = {'page': 'panel', 'time': 100, 'confirm_calls': 0, 'frames': 0}
    frames = iter(['panel', 'popup0', 'popup1', 'popup1', 'panel-old', 'panel-new'])

    def shot():
        state.update(page=next(frames), time=state['time'] + 1, frames=state['frames'] + 1)

    def confirm(*args):
        state['confirm_calls'] += 1
        return state['confirm_calls'] >= 2

    context = SimpleNamespace(
        device=SimpleNamespace(screenshot=shot, image=None),
        handover_panel_appear=lambda: state['page'].startswith('panel'),
        appear=lambda button, **kwargs: button is HANDOVER_EXCHANGE_CHECK and state['page'].startswith('popup'),
        appear_then_click=lambda button, **kwargs: button in (HANDOVER_EXCHANGE_TIME, HANDOVER_BOOK_ITEM),
        handle_popup_confirm=confirm, handle_popup_cancel=Mock(),
    )
    before = SimpleNamespace(last_valid=True, ocr=lambda image: timedelta(
        hours=2 if state['page'] == 'panel-new' else 1))
    inventory = SimpleNamespace(last_valid=True, ocr=lambda image: 10)
    added = SimpleNamespace(last_valid=True, ocr=lambda image: timedelta(
        hours=0 if state['page'] == 'popup0' else 1))
    with patch('module.base.timer.time', side_effect=lambda: state['time']), \
            patch('module.handover.handover.OCR_HANDOVER_TIME_REMAINING', before), \
            patch('module.handover.handover.OCR_HANDOVER_BOOK_AMOUNT', inventory), \
            patch('module.handover.handover.OCR_HANDOVER_EXCHANGE_ADDED', added):
        assert OperationHandover.handover_exchange_time(context, timedelta(seconds=1))
    assert state['frames'] == 6
    assert state['confirm_calls'] == 2


@pytest.mark.parametrize('dock_full', [False, True])
def test_continuous_sorties_delegate_to_the_existing_round_trip(dock_full):
    state = {'page': 'map'}
    entrance = SimpleNamespace(button=(0, 0, 10, 10))

    def battle():
        context.config.DOCK_FULL_TRIGGERED = dock_full
        state['page'] = 'result'
        raise CampaignEnd

    def click(*args, **kwargs):
        if state['page'] == 'result':
            state['page'] = 'chapter'
            return True
        return False

    context = SimpleNamespace(
        config=SimpleNamespace(Campaign_Mode='normal', Campaign_Use2xBook=False,
                               StopCondition_OilLimit=1000, StopCondition_OilLimitHardFloor=500),
        device=SimpleNamespace(screenshot=Mock(), screenshot_interval_set=Mock()),
        emotion=Mock(), map_get_info=Mock(), get_oil=lambda: 5000,
        MAP=object(), ENTRANCE=entrance, _map_battle=5, lv_reset=Mock(), enter_map=Mock(),
        multiple_sorties_result_appear=lambda: state['page'] == 'result',
        appear=lambda button: state['page'] == 'chapter', appear_then_click=click,
        handle_urgent_commission=lambda: False, handle_story_skip=lambda: False,
        auto_search_execute_a_battle=Mock(side_effect=battle),
    )
    assert MultipleSorties.run_multiple_sorties(context, 2) == (0 if dock_full else 2)
    context.auto_search_execute_a_battle.assert_called_once_with()
    assert context._multiple_sorties_requested == 0
    assert context._multiple_sorties_dock_interrupted is dock_full


def test_dock_full_during_result_uses_existing_cleanup_and_auto_search_resume():
    state = {'page': 'dock'}

    def frames():
        yield
        assert state['page'] == 'map'
        yield

    def cleanup():
        return state['page'] == 'dock'

    def resume():
        state['page'] = 'map'

    context = SimpleNamespace(
        device=Mock(), loop=frames, _withdraw=False, _defeat_count=0,
        _auto_search_status_confirm=True, combat_result=SimpleNamespace(defeated=False),
        handle_retirement=Mock(side_effect=cleanup), map_offensive_auto_search=Mock(side_effect=resume),
        appear=lambda *args, **kwargs: False, handle_combat_defeat=lambda: False,
        is_in_auto_search_menu=lambda: False, _handle_auto_search_menu_missing=lambda: False,
        is_auto_search_running=lambda: state['page'] == 'map',
    )
    for name in ('handle_urgent_commission', 'handle_story_skip', 'handle_guild_popup_cancel',
                 'handle_vote_popup', 'handle_mission_popup_ack', 'handle_get_ship',
                 'handle_get_items', 'handle_battle_status', 'handle_exp_info'):
        setattr(context, name, lambda: False)
    AutoSearchCombat.auto_search_combat_status(context)
    context.map_offensive_auto_search.assert_called_once_with()
    assert context.handle_retirement.call_count == 2
    assert not context._auto_search_status_confirm


def test_batch_stop_does_not_reenable_auto_search():
    context = SimpleNamespace(_multiple_sorties_stop_requested=True)
    assert not AutoSearchCombat.handle_auto_search_map_option(context)


def test_dock_prompt_marks_record_interrupted_before_cleanup_finishes():
    context = SimpleNamespace(
        _multiple_sorties_requested=1, _multiple_sorties_dock_interrupted=False,
        _unable_to_enhance=False, retirement_appear=lambda: True,
        config=SimpleNamespace(Retirement_RetireMode='one_click_retire'),
        appear_then_click=Mock(return_value=True), interval_clear=Mock(), interval_reset=Mock(),
        map_cat_attack_timer=Mock(),
    )
    Retirement.handle_retirement(context)
    assert context._multiple_sorties_dock_interrupted


@pytest.mark.parametrize('interrupted_completed', [0, 1])
def test_unlock_restarts_full_record_after_shared_dock_cleanup(interrupted_completed):
    campaign = SimpleNamespace(config=SimpleNamespace(MAP_IS_ONE_TIME_STAGE=False))
    interruptions = iter([True, False])

    def run(*args, **kwargs):
        campaign._multiple_sorties_dock_interrupted = next(interruptions)
        return interrupted_completed if campaign._multiple_sorties_dock_interrupted else 1

    campaign.run_multiple_sorties = Mock(side_effect=run)
    context = SimpleNamespace(
        campaign=campaign, config=SimpleNamespace(OperationHandover_OilLimit=1000),
        handover_enter=Mock(), handover_check_support=Mock(side_effect=[False, True]),
    )
    assert OperationHandover.handover_unlock(context)
    assert campaign.run_multiple_sorties.call_count == 2
    assert context.handover_check_support.call_count == 2


def test_unconfirmed_entry_after_dock_interruption_does_not_start_an_extra_sortie():
    campaign = SimpleNamespace(config=SimpleNamespace(MAP_IS_ONE_TIME_STAGE=False),
                               _multiple_sorties_dock_interrupted=True,
                               run_multiple_sorties=Mock(return_value=1))
    context = SimpleNamespace(
        campaign=campaign, config=SimpleNamespace(OperationHandover_OilLimit=1000),
        handover_enter=Mock(), handover_check_support=Mock(return_value=None),
    )
    assert not OperationHandover.handover_unlock(context)
    campaign.run_multiple_sorties.assert_called_once_with(1, oil_limit=1000)


def test_repeated_dock_interruptions_do_not_create_an_unbounded_unlock_loop():
    campaign = SimpleNamespace(config=SimpleNamespace(MAP_IS_ONE_TIME_STAGE=False),
                               _multiple_sorties_dock_interrupted=True,
                               run_multiple_sorties=Mock(return_value=0))
    context = SimpleNamespace(
        campaign=campaign, config=SimpleNamespace(OperationHandover_OilLimit=1000),
        handover_enter=Mock(), handover_check_support=Mock(return_value=False),
    )
    assert not OperationHandover.handover_unlock(context)
    assert campaign.run_multiple_sorties.call_count == 2


def run_context():
    config = SimpleNamespace(
        OperationHandover_Count=1, OperationHandover_AutoSupplementTime=False,
        OperationHandover_UseHandoverBook=False, OperationHandover_OilLimit=1000,
        OperationHandover_ConsumeAllBook=False, OperationHandover_MaintainOverride=False,
        Campaign_Name='5-2', task_delay=Mock(), cross_set=Mock(), task_stop=Mock(),
    )
    return SimpleNamespace(
        config=config, handover_consume_all_book_state=lambda: (False, ''),
        handover_maintain_state=lambda: (None, '', False),
        handover_commission_end=lambda: datetime(2020, 1, 1),
        handover_enter=Mock(), device=SimpleNamespace(screenshot=Mock()),
        appear=lambda *args, **kwargs: False, handover_reward=Mock(return_value=False),
        handover_commission_clear=Mock(), handover_check_support=Mock(return_value=True),
        get_oil=lambda: 5000, handover_panel_enter=Mock(), handover_close_panel=Mock(),
        handover_delay=Mock(), handover_consume_all_book_record=Mock(),
    )


@pytest.mark.parametrize('result', [0, -1])
def test_empty_inventory_or_failed_recognition_does_not_consume_weekly_trigger(result):
    context = run_context()
    context.config.OperationHandover_Count = 0
    context.config.OperationHandover_ConsumeAllBook = True
    context.handover_consume_all_book_state = lambda: (True, '')
    context.handover_consume_all_book = lambda: result
    OperationHandover.run(context)
    context.handover_consume_all_book_record.assert_not_called()
    context.handover_delay.assert_called_once_with()


def test_maintenance_day_claims_finished_commission_before_waiting_for_maintenance():
    now = datetime(2026, 11, 19, 2)
    context = run_context()
    context.handover_maintain_state = lambda: (now.replace(hour=10), '', True)
    context.handover_commission_end = lambda: now.replace(hour=1)
    context.handover_reward.return_value = True
    with patch('module.handover.handover.current_time', return_value=now):
        OperationHandover.run(context)
    context.handover_reward.assert_called_once_with()
    context.handover_commission_clear.assert_called_once_with()
    context.config.task_delay.assert_called_once_with(target=now.replace(hour=9, minute=50))
    context.handover_check_support.assert_not_called()


def test_disabling_new_commissions_keeps_existing_commission_scheduled_for_claim():
    now = datetime(2026, 11, 16, 12)
    context = run_context()
    context.config.OperationHandover_Count = 0
    context.handover_commission_end = lambda: now + timedelta(hours=1)
    with patch('module.handover.handover.current_time', return_value=now):
        OperationHandover.run(context)
    context.config.task_delay.assert_called_once_with(target=now + timedelta(hours=1))
    context.config.cross_set.assert_not_called()
    context.handover_enter.assert_not_called()


def test_transitional_disabled_button_does_not_trigger_an_unnecessary_sortie():
    state = {'frame': 0, 'time': 100}

    def shot():
        state['frame'] += 1
        state['time'] += 0.3

    context = SimpleNamespace(
        device=SimpleNamespace(screenshot=shot),
        appear=lambda button: (button is HANDOVER_TAB if state['frame'] >= 3
                               else button is HANDOVER_TAB_UNSUPPORTED),
    )
    with patch('module.base.timer.time', side_effect=lambda: state['time']):
        assert OperationHandover.handover_check_support(context)
