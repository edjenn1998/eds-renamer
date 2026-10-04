import os
from pathlib import Path
import pytest
from renamer.engine import Rename, execute, fingerprint
from renamer.session import create_transaction, load_transaction, newest_session
import renamer.engine as engine


def files(p):
    a,b=p/'a.txt',p/'b.txt';a.write_text('A');b.write_text('B');return a,b

@pytest.mark.parametrize('force',[False,True])
def test_direct_execute_duplicate_rejected(tmp_path,force):
    a,b=files(tmp_path);dest=tmp_path/'same.txt';tx=create_transaction(tmp_path/'state')
    with pytest.raises(ValueError):execute(tx,[Rename(a,dest),Rename(b,dest)],force)
    assert a.read_text()=='A' and b.read_text()=='B' and not dest.exists()


def test_undo_preserves_new_occupant(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.write_text('original')
    tx=create_transaction(tmp_path/'state');execute(tx,[Rename(a,b)]);a.write_text('new file')
    with pytest.raises(FileExistsError):tx.undo()
    assert a.read_text()=='new file' and b.read_text()=='original'


def test_undo_refuses_modified_renamed_file(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.write_text('original')
    tx=create_transaction(tmp_path/'state');execute(tx,[Rename(a,b)]);b.write_text('changed')
    with pytest.raises(ValueError):tx.undo()
    assert b.read_text()=='changed' and not a.exists()

@pytest.mark.parametrize('phase',[1,2,3,4])
def test_interrupt_after_move_recover_from_disk(tmp_path,monkeypatch,phase):
    a,b=files(tmp_path);tx=create_transaction(tmp_path/'state');real=engine._rename;count=0
    def crash(frm,to):
        nonlocal count
        count+=1;real(frm,to)
        if count==phase:raise KeyboardInterrupt()
    monkeypatch.setattr(engine,'_rename',crash)
    with pytest.raises(KeyboardInterrupt):execute(tx,[Rename(a,tmp_path/'x'),Rename(b,tmp_path/'y')])
    saved=load_transaction(tx.root,tx.id)
    assert len(saved.planned_moves)==4 and saved.pending
    monkeypatch.setattr(engine,'_rename',real);saved.recover()
    assert a.read_text()=='A' and b.read_text()=='B'
    assert not list(tmp_path.glob('.*renamer-*'))
    assert load_transaction(tx.root,tx.id).status=='rolled_back'


def test_crash_in_rollback_is_recoverable(tmp_path,monkeypatch):
    a,b=files(tmp_path);tx=create_transaction(tmp_path/'state');real=engine._rename;count=0
    def crash(frm,to):
        nonlocal count
        count+=1
        if count==3:raise OSError('forward failure')
        real(frm,to)
        if count==4:raise KeyboardInterrupt('rollback interrupted after move')
    monkeypatch.setattr(engine,'_rename',crash)
    with pytest.raises(KeyboardInterrupt):execute(tx,[Rename(a,tmp_path/'x'),Rename(b,tmp_path/'y')])
    monkeypatch.setattr(engine,'_rename',real);load_transaction(tx.root,tx.id).recover()
    assert a.read_text()=='A' and b.read_text()=='B'


def test_latest_skips_rolled_back_and_planned(tmp_path):
    a=tmp_path/'a';a.write_text('A');tx=create_transaction(tmp_path/'state');execute(tx,[Rename(a,tmp_path/'b')])
    other=create_transaction(tx.root);other.status='rolled_back';other.save();create_transaction(tx.root)
    assert newest_session(tx.root)==tx.id
    with pytest.raises(ValueError):other.undo()


def test_atomic_move_refuses_existing_destination(tmp_path):
    a,b=files(tmp_path)
    with pytest.raises(FileExistsError):engine._rename(str(a),str(b))
    assert a.read_text()=='A' and b.read_text()=='B'


def test_interrupted_transaction_blocks_new_batches(tmp_path,monkeypatch):
    a,b=files(tmp_path);tx=create_transaction(tmp_path/'state');real=engine._rename
    def crash(frm,to):real(frm,to);raise KeyboardInterrupt()
    monkeypatch.setattr(engine,'_rename',crash)
    with pytest.raises(KeyboardInterrupt):execute(tx,[Rename(a,tmp_path/'x')])
    monkeypatch.setattr(engine,'_rename',real)
    with pytest.raises(RuntimeError):execute(create_transaction(tx.root),[Rename(b,tmp_path/'y')])
    assert b.read_text()=='B'


def test_symlink_parent_alias_collision_refused(tmp_path):
    a,b=files(tmp_path);alias=tmp_path/'alias';alias.symlink_to(tmp_path,target_is_directory=True)
    tx=create_transaction(tmp_path/'state')
    with pytest.raises(ValueError):execute(tx,[Rename(a,tmp_path/'x'),Rename(b,alias/'x')])
    assert a.read_text()=='A' and b.read_text()=='B'


def test_force_undo_redo_contents(tmp_path):
    a,b=files(tmp_path);tx=create_transaction(tmp_path/'state');execute(tx,[Rename(a,b)],True)
    undo=tx.undo();assert a.read_text()=='A' and b.read_text()=='B'
    undo.undo();assert b.read_text()=='A' and not a.exists()


def test_invalid_direct_destination_and_missing_source(tmp_path):
    a,b=files(tmp_path)
    with pytest.raises(ValueError):execute(create_transaction(tmp_path/'state'),[Rename(a,tmp_path/'bad\x00')])
    assert a.read_text()=='A'
    with pytest.raises(ValueError):execute(create_transaction(tmp_path/'state'),[Rename(tmp_path/'absent',tmp_path/'c')])


def test_session_ids_cannot_escape_root(tmp_path):
    with pytest.raises(ValueError):create_transaction(tmp_path,sid='../outside')


def test_extension_strip_actually_removes_extension():
    from renamer.operations import ext_strip_op
    assert ext_strip_op()('photo','.jpg',0,1)==('photo','')


def test_destination_created_during_apply_is_preserved(tmp_path,monkeypatch):
    a=tmp_path/'a';b=tmp_path/'b';a.write_text('original');tx=create_transaction(tmp_path/'state')
    real=engine._rename;count=0
    def race(frm,to):
        nonlocal count
        count+=1
        if count==2:Path(to).write_text('external newcomer')
        real(frm,to)
    monkeypatch.setattr(engine,'_rename',race)
    with pytest.raises(FileExistsError):execute(tx,[Rename(a,b)])
    assert a.read_text()=='original' and b.read_text()=='external newcomer'
    assert load_transaction(tx.root,tx.id).status=='rolled_back'


def test_long_filename_can_be_renamed(tmp_path):
    a=tmp_path/('a'*250);a.write_text('A');b=tmp_path/'short'
    tx=create_transaction(tmp_path/'state');execute(tx,[Rename(a,b)]);tx.undo()
    assert a.read_text()=='A'


def test_noop_dry_run_does_not_create_state_dir(tmp_path):
    from renamer.cli import main
    a=tmp_path/'a.txt';a.write_text('A');state=tmp_path/'state'
    assert main(['--home',str(state),'rename',str(a),'--name','new'])==0
    assert a.read_text()=='A' and not state.exists()


def test_force_crash_after_backup_recovers_both(tmp_path,monkeypatch):
    a,b=files(tmp_path);tx=create_transaction(tmp_path/'state');real=engine._rename
    def crash(frm,to):real(frm,to);raise KeyboardInterrupt()
    monkeypatch.setattr(engine,'_rename',crash)
    with pytest.raises(KeyboardInterrupt):execute(tx,[Rename(a,b)],True)
    monkeypatch.setattr(engine,'_rename',real);load_transaction(tx.root,tx.id).recover()
    assert a.read_text()=='A' and b.read_text()=='B'


def test_recovery_refuses_new_occupant_then_can_resume(tmp_path,monkeypatch):
    a=tmp_path/'a';b=tmp_path/'b';a.write_text('A');tx=create_transaction(tmp_path/'state');real=engine._rename
    def crash(frm,to):real(frm,to);raise KeyboardInterrupt()
    monkeypatch.setattr(engine,'_rename',crash)
    with pytest.raises(KeyboardInterrupt):execute(tx,[Rename(a,b)])
    monkeypatch.setattr(engine,'_rename',real);a.write_text('new occupant')
    with pytest.raises((FileExistsError, ValueError)):load_transaction(tx.root,tx.id).recover()
    assert a.read_text()=='new occupant'
    a.unlink();load_transaction(tx.root,tx.id).recover();assert a.read_text()=='A'


def test_state_directory_cannot_be_renamed(tmp_path):
    tx=create_transaction(tmp_path/'state')
    with pytest.raises(ValueError):execute(tx,[Rename(tx.path(),tmp_path/'moved-journal')])
    assert tx.path().exists()


def test_managed_backup_not_selected_in_folder_scan(tmp_path):
    from renamer.engine import expand_paths
    a,b=files(tmp_path);tx=create_transaction(tmp_path/'state');execute(tx,[Rename(a,b)],True)
    backups=list(tmp_path.glob('.renamer-bak-*'));assert len(backups)==1
    assert backups[0] not in expand_paths([str(tmp_path)],False)
    with pytest.raises(ValueError):execute(create_transaction(tx.root),[Rename(backups[0],tmp_path/'backup-moved')])
    tx.undo();assert a.read_text()=='A' and b.read_text()=='B'


def test_original_list_format_journal_is_readable_but_not_undoable(tmp_path):
    import json
    folder=tmp_path/'sessions';folder.mkdir();(folder/'legacy.json').write_text(json.dumps([['/old','/new']]))
    tx=load_transaction(tmp_path,'legacy');assert tx.status=='completed' and len(tx.moves)==1
    with pytest.raises(ValueError,match='Legacy'):tx.undo()
