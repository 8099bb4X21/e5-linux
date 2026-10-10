"""Native DSP volume selection uses the loaded calibration, not DAC readback."""
import importlib.util
from pathlib import Path
import struct
import tempfile

source=Path(__file__).resolve().parents[1]/'overlay/opt/e5/e5-call-audio.py'
spec=importlib.util.spec_from_file_location('hardware',source)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    profile=Path(directory)/'audio_structure'
    blob=bytearray(struct.pack('<16sII',b'audio_profile',12,0x2da)+bytes(12*0x2da))
    # Deliberately nonmonotonic SWB entry and duplicate levels. The previous
    # maximum is index7; selecting the louder index4 would invert the volume UI.
    curve=(649,817,1154,10289,2053,2584,4096)
    struct.pack_into('<7H',blob,24+11*0x2da+0x244,*curve)
    profile.write_bytes(blob)
    hw=module.VoiceHardware.__new__(module.VoiceHardware)
    hw.volume_curves=hw.load_volume_curves(profile)
    hw.band=2;hw.speaker=True;hw.bluetooth=False
    steps=[]
    for level in range(1,16):
        hw.volume=level;steps.append(hw.dsp_volume())
    assert 4 not in steps and steps[0]==1 and steps[-1]==7
    audible=[curve[s-1] for s in steps]
    assert audible==sorted(audible) and max(audible)==curve[-1]
    assert len(set(audible))>=6, 'volume remained fixed at maximum'
    hw.bluetooth=True
    for level in range(16):
        hw.volume=level
        assert hw.dsp_volume()==7, 'changed the acoustically confirmed HFP path'
    profile.write_bytes(blob[:-2])
    assert hw.load_volume_curves(profile)=={}
    profile.write_bytes(struct.pack('<16sII',b'audio_profile',12,0x100)+bytes(12*0x100))
    assert hw.load_volume_curves(profile)=={}, 'guessed offsets in unknown AS layout'
print('PASS: native DSP gain varies, calibrated curve monotonic/capped, Bluetooth unchanged, invalid layout rejected')
with tempfile.TemporaryDirectory() as directory:
    codec=Path(directory)/'codec.xml'
    codec.write_text('''<codec><Audio><Handset><WB1 mode="2">
        <dacl_playback_volume><volume6 val="0x3"/></dacl_playback_volume>
        <ear_playback_volume><volume6 val="0x1"/></ear_playback_volume>
        </WB1></Handset><Handsfree><WB1 mode="9">
        <dacs_playback_volume><volume6 val="0x0"/></dacs_playback_volume>
        <ao_playback_volume><volume6 val="0x2"/></ao_playback_volume>
        </WB1></Handsfree></Audio></codec>''')
    gains=module.VoiceHardware.load_codec_gains(codec)
    assert gains[2]['ear_playback_volume']==1 and gains[9]['ao_playback_volume']==2
    codec.write_text('<!DOCTYPE codec [<!ENTITY bad "3">]><codec/>')
    assert module.VoiceHardware.load_codec_gains(codec)=={}
print('PASS: per-unit codec calibration and XML validation')
