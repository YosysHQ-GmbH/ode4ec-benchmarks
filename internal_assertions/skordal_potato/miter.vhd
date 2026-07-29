library ieee;
use ieee.std_logic_1164.all;

use work.pp_types.all;
use work.pp_utilities.all;

entity miter is 
  port (
        clk        : in std_logic;
        reset      : in std_logic;
        irq        : in std_logic_vector(7 downto 0);
        wb_dat_in  : in std_logic_vector(31 downto 0);
        wb_ack_in  : in std_logic
  );
end entity miter;

architecture formal of miter is

  component gold_top is
    port(
        clk              : in  std_logic;
        reset            : in  std_logic;
        irq              : in  std_logic_vector(7 downto 0);
        test_context_out : out test_context;
        wb_adr_out       : out std_logic_vector(31 downto 0);
        wb_sel_out       : out std_logic_vector( 3 downto 0);
        wb_cyc_out       : out std_logic;
        wb_stb_out       : out std_logic;
        wb_we_out        : out std_logic;
        wb_dat_out       : out std_logic_vector(31 downto 0);
        wb_dat_in        : in  std_logic_vector(31 downto 0);
        wb_ack_in        : in  std_logic
    );
  end component;

  component gate_top is
    port(
        clk              : in  std_logic;
        reset            : in  std_logic;
        irq              : in  std_logic_vector(7 downto 0);
        test_context_out : out test_context;
        wb_adr_out       : out std_logic_vector(31 downto 0);
        wb_sel_out       : out std_logic_vector( 3 downto 0);
        wb_cyc_out       : out std_logic;
        wb_stb_out       : out std_logic;
        wb_we_out        : out std_logic;
        wb_dat_out       : out std_logic_vector(31 downto 0);
        wb_dat_in        : in  std_logic_vector(31 downto 0);
        wb_ack_in        : in  std_logic
    );
  end component;

  signal gold_test_context : test_context;
  signal gold_wb_adr       : std_logic_vector(31 downto 0);
  signal gold_wb_sel       : std_logic_vector( 3 downto 0);
  signal gold_wb_cyc       : std_logic;
  signal gold_wb_stb       : std_logic;
  signal gold_wb_we        : std_logic;
  signal gold_wb_dat_out   : std_logic_vector(31 downto 0);
  
  signal gate_test_context : test_context;
  signal gate_wb_adr       : std_logic_vector(31 downto 0);
  signal gate_wb_sel       : std_logic_vector( 3 downto 0);
  signal gate_wb_cyc       : std_logic;
  signal gate_wb_stb       : std_logic;
  signal gate_wb_we        : std_logic;
  signal gate_wb_dat_out   : std_logic_vector(31 downto 0);

begin

    i_gold: gold_top
        port map (
            clk              => clk,
            reset            => reset,
            irq              => irq,
            test_context_out => gold_test_context,
            wb_adr_out       => gold_wb_adr,
            wb_sel_out       => gold_wb_sel,
            wb_cyc_out       => gold_wb_cyc,
            wb_stb_out       => gold_wb_stb,
            wb_we_out        => gold_wb_we,
            wb_dat_out       => gold_wb_dat_out,
            wb_dat_in        => wb_dat_in,
            wb_ack_in        => wb_ack_in
        );

    i_gate: gate_top
        port map (
            clk              => clk,
            reset            => reset,
            irq              => irq,
            test_context_out => gate_test_context,
            wb_adr_out       => gate_wb_adr,
            wb_sel_out       => gate_wb_sel,
            wb_cyc_out       => gate_wb_cyc,
            wb_stb_out       => gate_wb_stb,
            wb_we_out        => gate_wb_we,
            wb_dat_out       => gate_wb_dat_out,
            wb_dat_in        => wb_dat_in,
            wb_ack_in        => wb_ack_in
        );

    p_miter : process(clk)
    begin
        if rising_edge(clk) then

          assert gold_test_context = gate_test_context;
          assert gold_wb_adr = gate_wb_adr;
          assert gold_wb_sel = gate_wb_sel;
          assert gold_wb_cyc = gate_wb_cyc;
          assert gold_wb_stb = gate_wb_stb;
          assert gold_wb_we = gate_wb_we;
          assert gold_wb_dat_out = gate_wb_dat_out;

        end if;
    end process;

end architecture formal;
