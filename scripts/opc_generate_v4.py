            for i, r in enumerate(results)
        ],
    }
    (out_dir / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    print(f"\n{'='*50}")
    print(f"生成完成: {len(results)}篇 | 通过: {status['passed']} | 待修改: {status['needs_revision']}")
    if not args.no_repurpose:
        print(f"多渠道: {', '.join(args.channels)}")

    return 0


if __name__ == '__main__':
    sys.exit(main())