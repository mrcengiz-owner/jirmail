"""Gelen posta gönderen filtresi — kurumsal / toplu posta yanlış gizlenmesin."""
from webmail.sender import build_sender_info, should_block_inbound


def test_return_path_mismatch_does_not_block_paribu_style():
    info = build_sender_info(
        from_raw='Paribu <noreply@paribu.com>',
        return_path_raw='bounce@email.paribu.com',
        account_email='murat@mrcengiz.com',
        is_inbound=True,
        subject='E-posta doğrulama kodunuz',
    )
    assert info['is_spoofed'] is False
    assert should_block_inbound(info) is False


def test_verify_account_subject_does_not_block():
    info = build_sender_info(
        from_raw='Paribu <noreply@paribu.com>',
        account_email='murat@mrcengiz.com',
        is_inbound=True,
        subject='Verify your account',
    )
    assert info['is_probable_scam'] is False
    assert should_block_inbound(info) is False


def test_self_from_spoof_still_blocked():
    info = build_sender_info(
        from_raw='murat@mrcengiz.com',
        account_email='murat@mrcengiz.com',
        is_inbound=True,
        subject='Urgent payment required',
    )
    assert info['is_spoofed'] is True
    assert should_block_inbound(info) is True


def test_bitcoin_scam_body_still_blocked():
    info = build_sender_info(
        from_raw='attacker@evil.com',
        account_email='murat@mrcengiz.com',
        is_inbound=True,
        subject='Hello',
        snippet='Send bitcoin (btc) to my wallet address',
    )
    assert info['is_probable_scam'] is True
    assert should_block_inbound(info) is True
