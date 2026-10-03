// license:BSD-3-Clause
// copyright-holders:S1100FX contributors
/***************************************************************************
    S1100FX test machine

    MAME's Akai S1100 driver (s1000.cpp), booted without the boot ROM so
    S1100 OS files can be tested without ROM dumps. emu/mame/build.sh
    includes this file at the end of src/mame/akai/s1000.cpp.

    The real ROM loads the OS file from disk to physical address 0 and
    jumps to 0000:0040 (docs/os-map.md). This machine does the same from
    -quickload, which accepts either a raw OS file or an Akai S1000/S1100
    floppy image (the first OS file, type 0x63, is loaded from it):

        s1100fx s1100fx -quickload build/S1100FX.img -flop build/S1100FX.img

    Until a quickload is given, the CPU spins on a JMP $ at the reset
    vector. The L6009 sound ROMs are not needed for testing, so the sound
    ROM region is left empty.
***************************************************************************/

class s1100fx_state : public s1100_state
{
public:
	s1100fx_state(const machine_config &mconfig, device_type type, const char *tag)
		: s1100_state(mconfig, type, tag)
	{}

	void s1100fx(machine_config &config) ATTR_COLD;

protected:
	virtual void machine_start() override ATTR_COLD;
	virtual void machine_reset() override ATTR_COLD;

private:
	DECLARE_QUICKLOAD_LOAD_MEMBER(quickload_cb);
	std::string extract_os(const std::vector<u8> &file);
	void hle_boot();

	std::vector<u8> m_os;
};

/**************************************************************************/
void s1100fx_state::machine_start()
{
	s1100_state::machine_start();

	// JMP $ at the reset vector (FFFF:0000 -> ROM offset 0x3fff0)
	u8 *rom = memregion("maincpu")->base();
	rom[0x3fff0] = 0xeb;
	rom[0x3fff1] = 0xfe;
}

/**************************************************************************/
void s1100fx_state::machine_reset()
{
	s1100_state::machine_reset();
	if (!m_os.empty())
		hle_boot();
}

/**************************************************************************/
void s1100fx_state::hle_boot()
{
	address_space &prog = m_maincpu->space(AS_PROGRAM);
	for (size_t i = 0; i < m_os.size(); i++)
		prog.write_byte(i, m_os[i]);
	m_maincpu->set_state_int(NEC_PS, 0x0000);
	m_maincpu->set_state_int(NEC_PC, 0x0040);
	logerror("HLE boot: %u-byte OS at 0000:0000, entry 0000:0040\n", unsigned(m_os.size()));
}

/**************************************************************************/
// Returns an error message, or empty on success (m_os filled).
std::string s1100fx_state::extract_os(const std::vector<u8> &file)
{
	const size_t BLOCK = 1024, FAT = 0x600;
	const size_t nblocks = file.size() / BLOCK;

	if (file.size() != 819200 && file.size() != 1638400)
	{
		m_os = file; // raw OS memory image
		return std::string();
	}

	for (int slot = 0; slot < 64; slot++)
	{
		const u8 *e = &file[slot * 24];
		if (e[16] != 0x63) // 'c' = operating system
			continue;
		const u32 size = e[17] | (e[18] << 8) | (e[19] << 16);
		u32 blk = e[20] | (e[21] << 8);
		m_os.clear();
		while (m_os.size() < size)
		{
			if (blk >= nblocks)
				return util::string_format("OS file chain leaves the disk at block %u", blk);
			const u8 *src = &file[blk * BLOCK];
			const size_t n = std::min<size_t>(BLOCK, size - m_os.size());
			m_os.insert(m_os.end(), src, src + n);
			blk = file[FAT + 2 * blk] | (file[FAT + 2 * blk + 1] << 8);
			if (m_os.size() < size && blk >= 0x4000)
				return "OS file chain ends early";
		}
		logerror("disk image: OS file in slot %d, %u bytes\n", slot, size);
		return std::string();
	}
	return "no operating system file (type 0x63) on this disk image";
}

/**************************************************************************/
QUICKLOAD_LOAD_MEMBER(s1100fx_state::quickload_cb)
{
	std::vector<u8> file(image.length());
	if (image.fread(file.data(), file.size()) != file.size())
		return std::make_pair(image_error::UNSPECIFIED, std::string("read error"));

	std::string err = extract_os(file);
	if (!err.empty())
		return std::make_pair(image_error::INVALIDIMAGE, err);
	if (m_os.size() < 0x80 || m_os.size() > 0x80000)
		return std::make_pair(image_error::INVALIDLENGTH, std::string("OS must be 128 bytes to 512 KB"));

	hle_boot();
	return std::make_pair(std::error_condition(), std::string());
}

/**************************************************************************/
void s1100fx_state::s1100fx(machine_config &config)
{
	s1100(config);
	QUICKLOAD(config, "quickload", "bin,img").set_load_callback(FUNC(s1100fx_state::quickload_cb));
}

ROM_START( s1100fx )
	ROM_REGION(0x40000, "maincpu", ROMREGION_ERASEFF)
	ROM_REGION16_LE(0x20000, "l6009", ROMREGION_ERASE00)
ROM_END
