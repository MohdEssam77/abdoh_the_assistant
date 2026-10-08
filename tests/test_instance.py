import threading

from abdoh.instance import InstanceLock, ask_running_instance_to_show


def test_second_instance_is_refused_and_can_show_first(tmp_path):
    first = InstanceLock(tmp_path)
    assert first.acquire()
    shown = threading.Event()
    first.serve(on_show=shown.set)
    try:
        second = InstanceLock(tmp_path)
        assert not second.acquire()
        assert ask_running_instance_to_show(tmp_path)
        assert shown.wait(2)
    finally:
        first.release()
    third = InstanceLock(tmp_path)
    assert third.acquire()
    third.release()


def test_show_without_running_instance(tmp_path):
    assert ask_running_instance_to_show(tmp_path) is False
