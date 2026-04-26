using Microsoft.EntityFrameworkCore;
using BuildMeAPC.Api.Models;
using BuildMeAPC.Api.Models.Components;

namespace BuildMeAPC.Api.Data
{
    public class AppDbContext : DbContext
    {
        public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

        public DbSet<User> Users { get; set; }
        public DbSet<NewsArticle> NewsArticles { get; set; }
        public DbSet<SavedBuild> SavedBuilds { get; set; }
        public DbSet<BuildReport> BuildReports { get; set; }

        // Scraper-populated read-only component tables
        public DbSet<CpuEntity> Cpus { get; set; }
        public DbSet<GpuEntity> Gpus { get; set; }
        public DbSet<RamEntity> Rams { get; set; }
        public DbSet<MotherboardEntity> Motherboards { get; set; }
        public DbSet<SsdEntity> Ssds { get; set; }
        public DbSet<PsuEntity> Psus { get; set; }
        public DbSet<CaseEntity> Cases { get; set; }
        public DbSet<CoolerEntity> Coolers { get; set; }

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            // Ensure email is unique
            modelBuilder.Entity<User>()
                .HasIndex(u => u.Email)
                .IsUnique();

            // Scraper-owned tables: don't let EF try to create/migrate them
            modelBuilder.Entity<CpuEntity>().ToTable("cpus", t => t.ExcludeFromMigrations());
            modelBuilder.Entity<GpuEntity>().ToTable("gpus", t => t.ExcludeFromMigrations());
            modelBuilder.Entity<RamEntity>().ToTable("rams", t => t.ExcludeFromMigrations());
            modelBuilder.Entity<MotherboardEntity>().ToTable("motherboards", t => t.ExcludeFromMigrations());
            modelBuilder.Entity<SsdEntity>().ToTable("ssds", t => t.ExcludeFromMigrations());
            modelBuilder.Entity<PsuEntity>().ToTable("psus", t => t.ExcludeFromMigrations());
            modelBuilder.Entity<CaseEntity>().ToTable("cases", t => t.ExcludeFromMigrations());
            modelBuilder.Entity<CoolerEntity>().ToTable("coolers", t => t.ExcludeFromMigrations());
        }
    }
}
