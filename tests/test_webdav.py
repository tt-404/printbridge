"""WebDAV PROPFIND parsing: a folder listing must separate sub-folders from
files and exclude the queried folder itself, so the browser and Cloud->Print
act on the right entries.
"""
from printbridge.providers.webdav import _parse_children

_MULTISTATUS = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/user/PrintBridge/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/user/PrintBridge/ToPrint/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/user/PrintBridge/2026%20Rechnung.pdf</d:href>
    <d:propstat><d:prop><d:resourcetype/></d:prop></d:propstat>
  </d:response>
</d:multistatus>"""


def test_parse_separates_folders_and_files_and_decodes_names():
    children = _parse_children(_MULTISTATUS, "/remote.php/dav/files/user/PrintBridge")
    assert ("ToPrint", True) in children
    assert ("2026 Rechnung.pdf", False) in children  # %20 decoded
    # the folder itself is not listed
    assert all(name != "PrintBridge" for name, _ in children)
    assert len(children) == 2
