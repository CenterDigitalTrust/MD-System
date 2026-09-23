use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod md_system {
    use super::*;

    pub fn initialize_record(ctx: Context<InitializeRecord>) -> Result<()> {
        let record = &mut ctx.accounts.merkle_record;
        record.aggregator_pubkey = ctx.accounts.aggregator.key();
        // Изначально корень пустой
        record.root_hash = [0; 32];
        record.timestamp = Clock::get()?.unix_timestamp;
        
        msg!("Merkle record PDA initialized.");
        Ok(())
    }

    pub fn anchor_root(ctx: Context<AnchorRoot>, new_root_hash: [u8; 32]) -> Result<()> {
        let record = &mut ctx.accounts.merkle_record;
        
        // Проверка авторизации: только авторизованный агрегатор может писать в этот PDA
        require!(
            record.aggregator_pubkey == ctx.accounts.aggregator.key(),
            CustomError::UnauthorizedSigner
        );

        // Проверка, что мы не перезаписываем существующий корень просто так 
        // (в реальной системе здесь может быть логика аппенда или хранения истории через seed'ы, 
        // но для данного ТЗ мы можем просто обновлять PDA)
        // require!(record.root_hash == [0; 32], CustomError::RootAlreadyExists); // Раскомментировать, если 1 PDA = 1 Дерево намертво

        record.root_hash = new_root_hash;
        record.timestamp = Clock::get()?.unix_timestamp;
        
        msg!("Root anchored successfully");
        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializeRecord<'info> {
    #[account(
        init, 
        payer = aggregator, 
        space = 8 + 32 + 8 + 32, // discriminator(8) + root(32) + timestamp(8) + pubkey(32)
        seeds = [b"merkle_record", aggregator.key().as_ref()],
        bump
    )]
    pub merkle_record: Account<'info, MerkleRecord>,
    
    #[account(mut)]
    pub aggregator: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct AnchorRoot<'info> {
    #[account(
        mut,
        seeds = [b"merkle_record", aggregator.key().as_ref()],
        bump
    )]
    pub merkle_record: Account<'info, MerkleRecord>,
    
    #[account(mut)]
    pub aggregator: Signer<'info>,
}

#[account]
pub struct MerkleRecord {
    pub root_hash: [u8; 32],
    pub timestamp: i64,
    pub aggregator_pubkey: Pubkey,
}

#[error_code]
pub enum CustomError {
    #[msg("This root hash is already anchored.")]
    RootAlreadyExists,
    #[msg("Unauthorized signer. Only the designated aggregator can anchor.")]
    UnauthorizedSigner,
}
